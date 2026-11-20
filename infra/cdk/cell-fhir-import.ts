import {
  CfnOutput,
  CfnElement,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
  Validations,
} from "aws-cdk-lib";
import { PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { Key } from "aws-cdk-lib/aws-kms";
import {
  BlockPublicAccess,
  Bucket,
  BucketEncryption,
  ObjectOwnership,
} from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";

interface FhirImportProps extends StackProps {
  datastoreArn: string;
  stage: string;
  tenant: string;
}

export class CellFhirImport extends Stack {
  constructor(scope: Construct, id: string, props: FhirImportProps) {
    super(scope, id, props);
    this.node.setContext(
      "@aws-cdk/aws-s3:serverAccessLogsUseBucketPolicy",
      true,
    );
    if (
      !/^arn:aws:healthlake:[a-z0-9-]+:[0-9]{12}:datastore\/fhir\/[a-zA-Z0-9-]+$/.test(
        props.datastoreArn,
      )
    )
      throw new Error(
        "An explicit existing HealthLake datastore ARN is required",
      );
    Tags.of(this).add("Project", "verimed");
    Tags.of(this).add("Tenant", props.tenant);
    Tags.of(this).add("Env", props.stage);
    const key = new Key(this, "TransferKey", {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const logs = new Bucket(this, "AccessLogs", {
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    Validations.of(logs).acknowledge({
      id: "AwsSolutions::AwsSolutions-S1",
      reason:
        "This bucket is the access-log destination; self-logging would recurse.",
    });
    const transfer = new Bucket(this, "Transfer", {
      encryption: BucketEncryption.KMS,
      encryptionKey: key,
      bucketKeyEnabled: true,
      versioned: true,
      enforceSSL: true,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      objectOwnership: ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.RETAIN,
      serverAccessLogsBucket: logs,
      serverAccessLogsPrefix: "transfer/",
      lifecycleRules: [
        {
          prefix: "imports/",
          expiration: Duration.days(7),
          noncurrentVersionExpiration: Duration.days(7),
        },
      ],
    });
    const role = new Role(this, "DataAccessRole", {
      assumedBy: new ServicePrincipal("healthlake.amazonaws.com", {
        conditions: {
          StringEquals: { "aws:SourceAccount": this.account },
          ArnEquals: { "aws:SourceArn": props.datastoreArn },
        },
      }),
    });
    role.addToPolicy(
      new PolicyStatement({
        actions: ["s3:GetBucketLocation"],
        resources: [transfer.bucketArn],
      }),
    );
    role.addToPolicy(
      new PolicyStatement({
        actions: ["s3:ListBucket"],
        resources: [transfer.bucketArn],
        conditions: { StringLike: { "s3:prefix": ["imports/*"] } },
      }),
    );
    role.addToPolicy(
      new PolicyStatement({
        actions: ["s3:GetObject", "s3:GetObjectVersion"],
        resources: [transfer.arnForObjects("imports/*/input/*")],
      }),
    );
    role.addToPolicy(
      new PolicyStatement({
        actions: ["s3:PutObject"],
        resources: [transfer.arnForObjects("imports/*/output/*")],
      }),
    );
    role.addToPolicy(
      new PolicyStatement({
        actions: [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey",
        ],
        resources: [key.keyArn],
      }),
    );
    const bucketId = this.getLogicalId(
      transfer.node.defaultChild as CfnElement,
    );
    for (const path of ["input", "output"])
      Validations.of(role).acknowledge({
        id: `AwsSolutions::AwsSolutions-IAM5[Resource::<${bucketId}.Arn>/imports/*/${path}/*]`,
        reason:
          "Import job UUIDs require wildcard paths inside one dedicated bucket; service trust is bound to the exact datastore.",
      });
    new CfnOutput(this, "Bucket", { value: transfer.bucketName });
    new CfnOutput(this, "KeyArn", { value: key.keyArn });
    new CfnOutput(this, "DataAccessRoleArn", { value: role.roleArn });
    new CfnOutput(this, "DatastoreArn", { value: props.datastoreArn });
  }
}
