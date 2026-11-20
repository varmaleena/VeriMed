import {
  ArnFormat,
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
  Validations,
} from "aws-cdk-lib";
import { Alarm } from "aws-cdk-lib/aws-cloudwatch";
import {
  ISecurityGroup,
  IVpc,
  Peer,
  Port,
  SecurityGroup,
  SubnetType,
} from "aws-cdk-lib/aws-ec2";
import {
  Repository,
  RepositoryEncryption,
  TagMutability,
} from "aws-cdk-lib/aws-ecr";
import {
  AwsLogDriver,
  Cluster,
  ContainerImage,
  CpuArchitecture,
  FargateTaskDefinition,
  OperatingSystemFamily,
} from "aws-cdk-lib/aws-ecs";
import { PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { IKey, Key } from "aws-cdk-lib/aws-kms";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";
import { IBucket } from "aws-cdk-lib/aws-s3";
import {
  CustomState,
  DefinitionBody,
  LogLevel,
  StateMachine,
} from "aws-cdk-lib/aws-stepfunctions";
import { Construct } from "constructs";
import { CfnProject } from "aws-cdk-lib/aws-codebuild";
import { Asset } from "aws-cdk-lib/aws-s3-assets";

export interface CellSyntheaProps extends StackProps {
  stage: string;
  tenant: string;
  vpc: IVpc;
  endpointSecurityGroup: ISecurityGroup;
  s3PrefixListId: string;
  transferBucket: IBucket;
  transferKey: IKey;
  imageDigest?: string;
  buildContext?: string;
}

/** First deploy creates the image repository; the task is enabled only with a real digest. */
export class CellSynthea extends Stack {
  constructor(scope: Construct, id: string, props: CellSyntheaProps) {
    super(scope, id, props);
    if (props.imageDigest && !/^sha256:[a-f0-9]{64}$/.test(props.imageDigest))
      throw new Error("A verified immutable image digest is required");
    if (!/^pl-[a-f0-9]+$/.test(props.s3PrefixListId))
      throw new Error("Provide this region's S3 managed prefix list ID");
    for (const [name, value] of Object.entries({
      Project: "verimed",
      Env: props.stage,
      Tenant: props.tenant,
    }))
      Tags.of(this).add(name, value);
    const key = new Key(this, "Key", {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const repository = new Repository(this, "Repository", {
      encryption: RepositoryEncryption.KMS,
      encryptionKey: key,
      imageScanOnPush: true,
      imageTagMutability: TagMutability.IMMUTABLE,
      removalPolicy: RemovalPolicy.RETAIN,
      lifecycleRules: [{ maxImageCount: 10 }],
    });
    new CfnOutput(this, "RepositoryUri", { value: repository.repositoryUri });
    if (props.buildContext) {
      const source = new Asset(this, "BuildSource", {
        path: props.buildContext,
      });
      const buildLogName = `/verimed/${props.stage}/${props.tenant}/synthea-build`;
      const buildLogs = new LogGroup(this, "BuildLogs", {
        logGroupName: buildLogName,
        encryptionKey: key,
        retention: RetentionDays.ONE_MONTH,
        removalPolicy: RemovalPolicy.RETAIN,
      });
      key.addToResourcePolicy(
        new PolicyStatement({
          principals: [
            new ServicePrincipal(`logs.${this.region}.${this.urlSuffix}`),
          ],
          actions: [
            "kms:Encrypt",
            "kms:Decrypt",
            "kms:ReEncrypt*",
            "kms:GenerateDataKey*",
            "kms:DescribeKey",
          ],
          resources: ["*"],
          conditions: {
            ArnEquals: {
              "kms:EncryptionContext:aws:logs:arn": this.formatArn({
                service: "logs",
                resource: "log-group",
                resourceName: buildLogName,
                arnFormat: ArnFormat.COLON_RESOURCE_NAME,
              }),
            },
          },
        }),
      );
      const buildName = `verimed-${props.stage}-${props.tenant}-synthea`;
      const buildRole = new Role(this, "BuildRole", {
        assumedBy: new ServicePrincipal("codebuild.amazonaws.com", {
          conditions: {
            StringEquals: { "aws:SourceAccount": this.account },
            ArnEquals: {
              "aws:SourceArn": this.formatArn({
                service: "codebuild",
                resource: "project",
                resourceName: buildName,
              }),
            },
          },
        }),
      });
      buildRole.addToPolicy(
        new PolicyStatement({
          actions: ["s3:GetObject", "s3:GetObjectVersion"],
          resources: [source.bucket.arnForObjects(source.s3ObjectKey)],
        }),
      );
      buildRole.addToPolicy(
        new PolicyStatement({
          actions: ["s3:GetBucketLocation", "s3:GetBucketAcl"],
          resources: [source.bucket.bucketArn],
        }),
      );
      buildRole.addToPolicy(
        new PolicyStatement({
          actions: ["ecr:GetAuthorizationToken"],
          resources: ["*"],
        }),
      );
      buildRole.addToPolicy(
        new PolicyStatement({
          actions: [
            "ecr:BatchCheckLayerAvailability",
            "ecr:InitiateLayerUpload",
            "ecr:UploadLayerPart",
            "ecr:CompleteLayerUpload",
            "ecr:PutImage",
            "ecr:BatchGetImage",
            "ecr:GetDownloadUrlForLayer",
            "ecr:DescribeImageScanFindings",
          ],
          resources: [repository.repositoryArn],
        }),
      );
      buildRole.addToPolicy(
        new PolicyStatement({
          actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
          resources: [
            this.formatArn({
              service: "logs",
              resource: "log-group",
              resourceName: `${buildLogName}:log-stream:*`,
              arnFormat: ArnFormat.COLON_RESOURCE_NAME,
            }),
          ],
        }),
      );
      const builder = new CfnProject(this, "ImageBuild", {
        name: buildName,
        serviceRole: buildRole.roleArn,
        artifacts: { type: "NO_ARTIFACTS" },
        encryptionKey: key.keyArn,
        timeoutInMinutes: 25,
        queuedTimeoutInMinutes: 5,
        concurrentBuildLimit: 1,
        environment: {
          image: "aws/codebuild/amazonlinux-aarch64-standard:4.0",
          type: "ARM_CONTAINER",
          computeType: "BUILD_GENERAL1_SMALL",
          privilegedMode: true,
          environmentVariables: [
            { name: "IMAGE_URI", value: repository.repositoryUri },
            { name: "IMAGE_TAG", value: `source-${source.assetHash}` },
          ],
        },
        logsConfig: {
          cloudWatchLogs: {
            status: "ENABLED",
            groupName: buildLogs.logGroupName,
          },
        },
        source: {
          type: "S3",
          location: `${source.s3BucketName}/${source.s3ObjectKey}`,
          buildSpec: JSON.stringify({
            version: "0.2",
            phases: {
              pre_build: {
                commands: [
                  "set -eu",
                  'aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${IMAGE_URI%%/*}"',
                ],
              },
              build: {
                commands: [
                  'docker build --platform linux/arm64 -f services/simulator/container/Dockerfile -t "$IMAGE_URI:$IMAGE_TAG" .',
                  'docker run --rm --network none --read-only --memory 2g --cpus 1 --cap-drop ALL --security-opt no-new-privileges --entrypoint timeout "$IMAGE_URI:$IMAGE_TAG" --signal=TERM --kill-after=20s 10m python -m simulator.container_smoke',
                ],
              },
              post_build: {
                commands: [
                  'test "$CODEBUILD_BUILD_SUCCEEDING" = 1',
                  'docker push "$IMAGE_URI:$IMAGE_TAG"',
                  'aws ecr wait image-scan-complete --repository-name "${IMAGE_URI#*/}" --image-id "imageTag=$IMAGE_TAG"',
                  'aws ecr describe-image-scan-findings --repository-name "${IMAGE_URI#*/}" --image-id "imageTag=$IMAGE_TAG" --query imageScanFindings.findingSeverityCounts --output json > /tmp/image-scan-counts.json',
                  'python3 -c \'import json,sys; c=json.load(open("/tmp/image-scan-counts.json")); sys.exit(0 if isinstance(c,dict) and c.get("HIGH",0)==0 and c.get("CRITICAL",0)==0 else 1)\'',
                ],
              },
            },
          }),
        },
      });
      Validations.of(builder).acknowledge({
        id: "AwsSolutions::AwsSolutions-CB3",
        reason:
          "Docker image builds require a privileged daemon on an isolated, short-lived CodeBuild worker. Only owner-built allowlisted source is accepted; no PR webhooks or cell clinical-data permissions exist.",
      });
      Validations.of(buildRole).acknowledge({
        id: "AwsSolutions::AwsSolutions-IAM5[Resource::*]",
        reason:
          "ECR GetAuthorizationToken cannot be resource-scoped; push/pull actions are restricted to the single Synthea repository.",
      });
      Validations.of(buildRole).acknowledge({
        id: `AwsSolutions::AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:logs:${this.region}:${this.account}:log-group:${buildLogName}:log-stream:*]`,
        reason:
          "CodeBuild creates a stream per run within this one pre-created encrypted log group.",
      });
      new CfnOutput(this, "BuildProject", { value: builder.ref });
      new CfnOutput(this, "BuildImageTag", {
        value: `source-${source.assetHash}`,
      });
    }
    if (!props.imageDigest) return;

    const logName = `/verimed/${props.stage}/${props.tenant}/synthea`;
    const stateLogName = `${logName}-workflow`;
    key.addToResourcePolicy(
      new PolicyStatement({
        principals: [
          new ServicePrincipal(`logs.${this.region}.${this.urlSuffix}`),
        ],
        actions: [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
        ],
        resources: ["*"],
        conditions: {
          ArnEquals: {
            "kms:EncryptionContext:aws:logs:arn": [logName, stateLogName].map(
              (resourceName) =>
                this.formatArn({
                  service: "logs",
                  resource: "log-group",
                  resourceName,
                  arnFormat: ArnFormat.COLON_RESOURCE_NAME,
                }),
            ),
          },
        },
      }),
    );
    const logs = new LogGroup(this, "TaskLogs", {
      logGroupName: logName,
      encryptionKey: key,
      retention: RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const workflowLogs = new LogGroup(this, "WorkflowLogs", {
      logGroupName: stateLogName,
      encryptionKey: key,
      retention: RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const cluster = new Cluster(this, "Cluster", { vpc: props.vpc });
    const group = new SecurityGroup(this, "TaskSecurityGroup", {
      vpc: props.vpc,
      allowAllOutbound: false,
      description:
        "Synthea task: endpoints and S3 only; no inbound connections",
    });
    group.addEgressRule(props.endpointSecurityGroup, Port.tcp(443));
    props.endpointSecurityGroup.addIngressRule(
      group,
      Port.tcp(443),
      "Synthea ECR and log endpoints",
      true,
    );
    group.addEgressRule(Peer.prefixList(props.s3PrefixListId), Port.tcp(443));
    const task = new FargateTaskDefinition(this, "Task", {
      cpu: 1024,
      memoryLimitMiB: 2048,
      runtimePlatform: {
        cpuArchitecture: CpuArchitecture.ARM64,
        operatingSystemFamily: OperatingSystemFamily.LINUX,
      },
    });
    task.addVolume({ name: "work" });
    const container = task.addContainer("generator", {
      image: ContainerImage.fromEcrRepository(repository, props.imageDigest),
      user: "10001:10001",
      readonlyRootFilesystem: true,
      stopTimeout: Duration.seconds(30),
      logging: new AwsLogDriver({ logGroup: logs, streamPrefix: "generator" }),
      environment: {
        AWS_REGION: this.region,
        CELL_ACCOUNT: this.account,
        TRANSFER_BUCKET: props.transferBucket.bucketName,
        TRANSFER_KEY_ARN: props.transferKey.keyArn,
      },
    });
    container.addMountPoints({
      sourceVolume: "work",
      containerPath: "/work",
      readOnly: false,
    });
    task.addToTaskRolePolicy(
      new PolicyStatement({
        actions: ["s3:PutObject"],
        resources: [
          props.transferBucket.arnForObjects(
            "imports/*/input/resources.ndjson",
          ),
          props.transferBucket.arnForObjects("imports/*/metadata/*.json"),
        ],
        conditions: {
          StringEquals: {
            "s3:x-amz-server-side-encryption": "aws:kms",
            "s3:x-amz-server-side-encryption-aws-kms-key-id":
              props.transferKey.keyArn,
          },
        },
      }),
    );
    task.addToTaskRolePolicy(
      new PolicyStatement({
        actions: ["kms:GenerateDataKey", "kms:Decrypt"],
        resources: [props.transferKey.keyArn],
        conditions: {
          StringEquals: {
            "kms:ViaService": `s3.${this.region}.${this.urlSuffix}`,
          },
        },
      }),
    );
    // Explicit integration avoids the L2 helper granting RunTask on every family revision.
    const run = new CustomState(this, "GenerateAndUpload", {
      stateJson: {
        Type: "Task",
        Resource: `arn:${this.partition}:states:::ecs:runTask.sync`,
        Parameters: {
          Cluster: cluster.clusterArn,
          TaskDefinition: task.taskDefinitionArn,
          LaunchType: "FARGATE",
          PlatformVersion: "LATEST",
          NetworkConfiguration: {
            AwsvpcConfiguration: {
              AssignPublicIp: "DISABLED",
              SecurityGroups: [group.securityGroupId],
              Subnets: props.vpc.selectSubnets({
                subnetType: SubnetType.PRIVATE_ISOLATED,
              }).subnetIds,
            },
          },
          Overrides: {
            ContainerOverrides: [
              {
                Name: container.containerName,
                Environment: [
                  { Name: "JOB_ID", "Value.$": "$.job_id" },
                  {
                    Name: "POPULATION",
                    "Value.$": "States.Format('{}', $.population)",
                  },
                ],
              },
            ],
          },
        },
      },
    });
    const workflow = new StateMachine(this, "Workflow", {
      definitionBody: DefinitionBody.fromChainable(run),
      timeout: Duration.minutes(40),
      logs: {
        destination: workflowLogs,
        level: LogLevel.ALL,
        includeExecutionData: false,
      },
      tracingEnabled: true,
    });
    workflow.addToRolePolicy(
      new PolicyStatement({
        actions: ["ecs:RunTask"],
        resources: [task.taskDefinitionArn],
        conditions: { ArnEquals: { "ecs:cluster": cluster.clusterArn } },
      }),
    );
    workflow.addToRolePolicy(
      new PolicyStatement({
        actions: ["ecs:StopTask", "ecs:DescribeTasks"],
        resources: ["*"],
        conditions: { ArnEquals: { "ecs:cluster": cluster.clusterArn } },
      }),
    );
    workflow.addToRolePolicy(
      new PolicyStatement({
        actions: ["events:PutRule", "events:PutTargets", "events:DescribeRule"],
        resources: [
          this.formatArn({
            service: "events",
            resource: "rule",
            resourceName: "StepFunctionsGetEventsForECSTaskRule",
          }),
        ],
      }),
    );
    workflow.addToRolePolicy(
      new PolicyStatement({
        actions: ["iam:PassRole"],
        resources: [task.taskRole.roleArn, task.executionRole!.roleArn],
        conditions: {
          StringEquals: { "iam:PassedToService": "ecs-tasks.amazonaws.com" },
        },
      }),
    );
    new Alarm(this, "GenerationFailed", {
      metric: workflow.metricFailed(),
      threshold: 1,
      evaluationPeriods: 1,
    });
    Validations.of(task).acknowledge({
      id: "AwsSolutions::AwsSolutions-ECS2",
      reason:
        "Only region, account, bucket and KMS ARN are environment configuration; no secrets, PHI or patient identifiers are injected.",
    });
    for (const path of ["input/resources.ndjson", "metadata/*.json"])
      Validations.of(task.taskRole).acknowledge({
        id: `AwsSolutions::AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:s3:::${props.transferBucket.bucketName}/imports/*/${path}]`,
        reason:
          "PutObject is restricted to runtime job UUID paths in the single cell transfer bucket. No reads, deletes, listing or access to another tenant bucket are granted.",
      });
    Validations.of(task.executionRole!).acknowledge({
      id: "AwsSolutions::AwsSolutions-IAM5[Resource::*]",
      reason:
        "ECR GetAuthorizationToken has no resource-level ARN. Image layer reads are separately restricted to this repository by CDK.",
    });
    Validations.of(workflow.role).acknowledge({
      id: "AwsSolutions::AwsSolutions-IAM5[Resource::*]",
      reason:
        "CDK ECS sync integration needs unknown runtime task IDs; RunTask is confined to the exact deployed revision and PassRole to its two roles. CloudWatch delivery and X-Ray APIs do not support resource scoping. No clinical payloads are logged.",
    });
    Validations.of(cluster).acknowledge({
      id: "AwsSolutions::AwsSolutions-ECS4",
      reason:
        "On-demand bounded generator has no service fleet; task logs and workflow failures provide diagnostics without recurring Container Insights cost.",
    });
    new CfnOutput(this, "WorkflowArn", { value: workflow.stateMachineArn });
  }
}
