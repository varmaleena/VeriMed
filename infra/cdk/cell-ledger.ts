import {
  CfnOutput,
  Duration,
  ArnFormat,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
  Validations,
} from "aws-cdk-lib";
import { Key, KeySpec, KeyUsage } from "aws-cdk-lib/aws-kms";
import {
  Bucket,
  BucketEncryption,
  BlockPublicAccess,
  CfnBucket,
  ObjectOwnership,
} from "aws-cdk-lib/aws-s3";
import {
  AnyPrincipal,
  PolicyStatement,
  Effect,
  Role,
  ServicePrincipal,
} from "aws-cdk-lib/aws-iam";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { SqsDestination } from "aws-cdk-lib/aws-lambda-destinations";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";
import { Queue, QueueEncryption } from "aws-cdk-lib/aws-sqs";
import { Rule, Schedule, RuleTargetInput } from "aws-cdk-lib/aws-events";
import { LambdaFunction } from "aws-cdk-lib/aws-events-targets";
import {
  Metric,
  TreatMissingData,
  ComparisonOperator,
} from "aws-cdk-lib/aws-cloudwatch";
import { Construct } from "constructs";

interface LedgerProps extends StackProps {
  stage: string;
  tenant: string;
  worker?: {
    bundle: string;
    tenantId: string;
    clusterArn: string;
    readerSecretArn: string;
    databaseKeyArn: string;
    reserveConcurrency?: boolean;
  };
}

export class CellLedger extends Stack {
  constructor(scope: Construct, id: string, props: LedgerProps) {
    super(scope, id, props);
    this.node.setContext(
      "@aws-cdk/aws-s3:serverAccessLogsUseBucketPolicy",
      true,
    );
    Tags.of(this).add("Project", "verimed");
    Tags.of(this).add("Tenant", props.tenant);
    Tags.of(this).add("Env", props.stage);
    const signingKey = new Key(this, "SigningKey", {
      description: "ChartVigil tenant audit ledger signatures",
      keySpec: KeySpec.ECC_NIST_P256,
      keyUsage: KeyUsage.SIGN_VERIFY,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    // AWS KMS automatic rotation supports symmetric encryption keys only.
    // Rotate by provisioning a new key, retaining old ARNs for historical verification.
    Validations.of(signingKey).acknowledge({
      id: "AwsSolutions::AwsSolutions-KMS4",
      reason:
        "Asymmetric signing keys do not support automatic rotation; retain historical keys and rotate through new versioned keys.",
    });
    new CfnOutput(this, "SigningKeyArn", { value: signingKey.keyArn });
    const anchorKey = new Key(this, "AnchorKey", {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
      description: "ChartVigil retained ledger anchor encryption",
    });
    const accessLogs = new Bucket(this, "AnchorAccessLogs", {
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    Validations.of(accessLogs).acknowledge({
      id: "AwsSolutions::AwsSolutions-S1",
      reason:
        "This is the destination for anchor bucket access logs; logging it to itself would recurse.",
    });
    const anchors = new Bucket(this, "Anchors", {
      encryption: BucketEncryption.KMS,
      encryptionKey: anchorKey,
      bucketKeyEnabled: true,
      versioned: true,
      objectLockEnabled: true,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.RETAIN,
      serverAccessLogsBucket: accessLogs,
      serverAccessLogsPrefix: "anchors/",
    });
    const cfnAnchors = anchors.node.defaultChild as CfnBucket;
    cfnAnchors.objectLockConfiguration = {
      objectLockEnabled: "Enabled",
      rule: { defaultRetention: { mode: "COMPLIANCE", years: 7 } },
    };
    anchors.addToResourcePolicy(
      new PolicyStatement({
        effect: Effect.DENY,
        principals: [new AnyPrincipal()],
        actions: ["s3:DeleteObject"],
        resources: [anchors.arnForObjects("*")],
      }),
    );
    anchors.addToResourcePolicy(
      new PolicyStatement({
        effect: Effect.DENY,
        principals: [new AnyPrincipal()],
        actions: ["s3:PutObject"],
        resources: [anchors.arnForObjects("*")],
        conditions: { Null: { "s3:if-none-match": "true" } },
      }),
    );
    new CfnOutput(this, "AnchorBucketName", { value: anchors.bucketName });
    new CfnOutput(this, "AnchorEncryptionKeyArn", { value: anchorKey.keyArn });
    if (props.worker) {
      const settings = props.worker;
      const logName = `/verimed/${props.stage}/${props.tenant}/ledger-anchor-worker`;
      anchorKey.addToResourcePolicy(
        new PolicyStatement({
          principals: [
            new ServicePrincipal(`logs.${this.region}.${this.urlSuffix}`),
          ],
          actions: [
            "kms:Encrypt",
            "kms:Decrypt",
            "kms:ReEncryptFrom",
            "kms:ReEncryptTo",
            "kms:GenerateDataKey",
            "kms:GenerateDataKeyWithoutPlaintext",
            "kms:DescribeKey",
          ],
          resources: ["*"],
          conditions: {
            ArnEquals: {
              "kms:EncryptionContext:aws:logs:arn": this.formatArn({
                service: "logs",
                resource: "log-group",
                resourceName: logName,
                arnFormat: ArnFormat.COLON_RESOURCE_NAME,
              }),
            },
          },
        }),
      );
      const logs = new LogGroup(this, "WorkerLogs", {
        logGroupName: logName,
        encryptionKey: anchorKey,
        retention: RetentionDays.ONE_MONTH,
        removalPolicy: RemovalPolicy.RETAIN,
      });
      const deadLetters = new Queue(this, "WorkerDeadLetters", {
        encryption: QueueEncryption.KMS,
        encryptionMasterKey: anchorKey,
        retentionPeriod: Duration.days(14),
        enforceSSL: true,
      });
      const role = new Role(this, "WorkerRole", {
        assumedBy: new ServicePrincipal("lambda.amazonaws.com"),
      });
      logs.grantWrite(role);
      role.addToPolicy(
        new PolicyStatement({
          actions: [
            "rds-data:ExecuteStatement",
            "rds-data:BeginTransaction",
            "rds-data:CommitTransaction",
            "rds-data:RollbackTransaction",
          ],
          resources: [settings.clusterArn],
        }),
      );
      role.addToPolicy(
        new PolicyStatement({
          actions: ["secretsmanager:GetSecretValue"],
          resources: [settings.readerSecretArn],
        }),
      );
      role.addToPolicy(
        new PolicyStatement({
          actions: ["kms:Decrypt"],
          resources: [settings.databaseKeyArn],
          conditions: {
            StringEquals: {
              "kms:ViaService": `secretsmanager.${this.region}.${this.urlSuffix}`,
              "kms:EncryptionContext:SecretARN": settings.readerSecretArn,
            },
          },
        }),
      );
      const prefix = `anchors/${settings.tenantId}/`;
      role.addToPolicy(
        new PolicyStatement({
          actions: ["s3:ListBucketVersions"],
          resources: [anchors.bucketArn],
          conditions: { StringLike: { "s3:prefix": `${prefix}*` } },
        }),
      );
      role.addToPolicy(
        new PolicyStatement({
          actions: [
            "s3:GetObject",
            "s3:GetObjectVersion",
            "s3:GetObjectRetention",
            "s3:PutObject",
          ],
          resources: [anchors.arnForObjects(`${prefix}*`)],
        }),
      );
      signingKey.grant(role, "kms:Sign", "kms:Verify");
      anchorKey.grantEncryptDecrypt(role);
      const worker = new Function(this, "AnchorWorker", {
        runtime: Runtime.PYTHON_3_12,
        architecture: Architecture.ARM_64,
        code: Code.fromAsset(settings.bundle),
        handler: "app.ledger_worker.handler",
        role,
        memorySize: 512,
        timeout: Duration.minutes(5),
        reservedConcurrentExecutions:
          settings.reserveConcurrency === false ? undefined : 1,
        logGroup: logs,
        retryAttempts: 2,
        maxEventAge: Duration.hours(2),
        onFailure: new SqsDestination(deadLetters),
        environment: {
          TENANT_ID: settings.tenantId,
          DATABASE_CLUSTER_ARN: settings.clusterArn,
          DATABASE_SECRET_ARN: settings.readerSecretArn,
          LEDGER_SIGNING_KEY_ARN: signingKey.keyArn,
          LEDGER_ANCHOR_BUCKET: anchors.bucketName,
          LEDGER_ANCHOR_KEY_ARN: anchorKey.keyArn,
        },
      });
      const daily = new Rule(this, "DailyAnchor", {
        schedule: Schedule.cron({ minute: "30", hour: "0" }),
        description: "Daily cell ledger checkpoint at 00:30 UTC",
      });
      daily.addTarget(
        new LambdaFunction(worker, {
          event: RuleTargetInput.fromObject({ job: "daily" }),
          deadLetterQueue: deadLetters,
          retryAttempts: 2,
          maxEventAge: Duration.hours(2),
        }),
      );
      worker
        .metricErrors({ period: Duration.minutes(5) })
        .createAlarm(this, "WorkerFailureAlarm", {
          threshold: 1,
          evaluationPeriods: 1,
          treatMissingData: TreatMissingData.NOT_BREACHING,
        });
      deadLetters
        .metricApproximateNumberOfMessagesVisible({
          period: Duration.minutes(5),
        })
        .createAlarm(this, "WorkerDeadLetterAlarm", {
          threshold: 1,
          evaluationPeriods: 1,
          treatMissingData: TreatMissingData.NOT_BREACHING,
        });
      new Metric({
        namespace: "VeriMed",
        metricName: "LedgerAnchorJobSuccess",
        statistic: "Sum",
        period: Duration.hours(1),
      }).createAlarm(this, "WorkerHeartbeatAlarm", {
        threshold: 1,
        comparisonOperator: ComparisonOperator.LESS_THAN_THRESHOLD,
        evaluationPeriods: 36,
        datapointsToAlarm: 36,
        treatMissingData: TreatMissingData.BREACHING,
      });
      for (const [target, rule, reason] of [
        [
          worker,
          "L1",
          "Python 3.12 follows the project specification; the scheduled worker has bounded runtime and concurrency.",
        ],
        [
          role,
          "IAM5",
          "Wildcard resources cover only this tenant's anchor objects and the worker's log streams; no other tenant prefix, administrator secret, or ledger writer credential is granted.",
        ],
        [
          deadLetters,
          "SQS3",
          "This queue is the terminal dead-letter destination for schedule delivery and Lambda execution failures; it must not redrive to itself.",
        ],
      ] as const) {
        Validations.of(target).acknowledge({
          id: `AwsSolutions::AwsSolutions-${rule}`,
          reason,
        });
      }
      const workerPolicy = role.node
        .findChild("DefaultPolicy")
        .node.findChild("Resource");
      for (const detail of [
        `Resource::<${this.getLogicalId(cfnAnchors)}.Arn>/anchors/${settings.tenantId}/*`,
        "Action::kms:ReEncrypt*",
        "Action::kms:GenerateDataKey*",
      ]) {
        Validations.of(workerPolicy).acknowledge({
          id: `AwsSolutions::AwsSolutions-IAM5[${detail}]`,
          reason:
            "The object wildcard is limited to this cell tenant's anchor prefix. CDK KMS encryption helpers use action families scoped to the retained anchor CMK for S3 and encrypted DLQ delivery.",
        });
      }
      new CfnOutput(this, "AnchorWorkerName", { value: worker.functionName });
      new CfnOutput(this, "AnchorWorkerRoleArn", { value: role.roleArn });
      new CfnOutput(this, "AnchorScheduleName", { value: daily.ruleName });
      new CfnOutput(this, "AnchorDeadLetterQueueUrl", {
        value: deadLetters.queueUrl,
      });
    }
  }
}
