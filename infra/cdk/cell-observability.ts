import {
  ArnFormat,
  CfnOutput,
  CustomResource,
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
  CfnResourcePolicy,
  LogGroup,
  RetentionDays,
} from "aws-cdk-lib/aws-logs";
import { CfnTransactionSearchConfig } from "aws-cdk-lib/aws-xray";
import { Construct } from "constructs";
import { Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { SPAN_RETENTION_HANDLER } from "./span-retention-handler";

interface CellObservabilityProps extends StackProps {
  stage: string;
  tenant: string;
}

/** Account/region singleton: one structurally isolated cell per AWS account. */
export class CellObservability extends Stack {
  constructor(scope: Construct, id: string, props: CellObservabilityProps) {
    super(scope, id, props);
    for (const [name, value] of Object.entries({
      Project: "verimed",
      Tenant: props.tenant,
      Env: props.stage,
    }))
      Tags.of(this).add(name, value);
    const names = ["aws/spans", "/aws/application-signals/data"];
    const key = new Key(this, "TraceKey", {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const arns = names.map((resourceName) =>
      this.formatArn({
        service: "logs",
        resource: "log-group",
        resourceName,
        arnFormat: ArnFormat.COLON_RESOURCE_NAME,
      }),
    );
    const helperName = `/verimed/${props.stage}/${props.tenant}/trace-retention`;
    const helperArn = this.formatArn({
      service: "logs",
      resource: "log-group",
      resourceName: helperName,
      arnFormat: ArnFormat.COLON_RESOURCE_NAME,
    });
    key.addToResourcePolicy(
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
            "kms:EncryptionContext:aws:logs:arn": [...arns, helperArn],
          },
        },
      }),
    );
    const dataLogs = new LogGroup(this, "DataLogs", {
      logGroupName: names[1],
      encryptionKey: key,
      retention: RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const access = new CfnResourcePolicy(this, "XrayDelivery", {
      policyName: `verimed-${props.stage}-${props.tenant}-xray-delivery`,
      policyDocument: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: { Service: "xray.amazonaws.com" },
            Action: "logs:PutLogEvents",
            Resource: arns.map((arn) => `${arn}:*`),
            Condition: {
              StringEquals: { "aws:SourceAccount": this.account },
              ArnLike: {
                "aws:SourceArn": this.formatArn({
                  service: "xray",
                  resource: "*",
                }),
              },
            },
          },
        ],
      }),
    });
    const search = new CfnTransactionSearchConfig(this, "TransactionSearch", {
      indexingPercentage: 1,
      cloudWatchLogsConfiguration: { spansLogGroupKmsKeyId: key.keyArn },
    });
    Validations.of(search).acknowledge({
      id: "CloudFormation-Validate::F3002",
      reason:
        "The live us-east-1 CloudFormation DescribeType schema includes CloudWatchLogsConfiguration (verified 2026-11-20), as do current AWS docs. The bundled validation schema is older.",
    });
    // aws/spans is an AWS-reserved name. X-Ray must create it using this CMK.
    search.node.addDependency(dataLogs);
    search.node.addDependency(access);
    const helperLogs = new LogGroup(this, "RetentionLogs", {
      logGroupName: helperName,
      encryptionKey: key,
      retention: RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const helperRole = new Role(this, "RetentionRole", {
      assumedBy: new ServicePrincipal("lambda.amazonaws.com"),
    });
    helperRole.addToPolicy(
      new PolicyStatement({
        actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
        resources: [`${helperArn}:log-stream:*`],
      }),
    );
    helperRole.addToPolicy(
      new PolicyStatement({
        actions: ["logs:PutRetentionPolicy"],
        resources: [`${arns[0]}:*`],
      }),
    );
    const helper = new Function(this, "RetentionHelper", {
      runtime: Runtime.NODEJS_24_X,
      handler: "index.handler",
      code: Code.fromInline(SPAN_RETENTION_HANDLER),
      role: helperRole,
      logGroup: helperLogs,
      timeout: Duration.seconds(30),
    });
    Validations.of(helper).acknowledge({
      id: "AwsSolutions::AwsSolutions-L1",
      reason:
        "Node.js 24 is the current supported GA runtime. AWS lists Node.js 26 as public preview, outside the Lambda SLA; a preview is unsuitable for the infrastructure helper. Verified in AWS runtime docs on 2026-11-20.",
    });
    const retention = new CustomResource(this, "SpansRetention", {
      serviceToken: helper.functionArn,
      resourceType: "Custom::VerimedSpansRetention",
      properties: { LogGroupName: names[0], RetentionInDays: 30 },
      serviceTimeout: Duration.minutes(1),
    });
    retention.node.addDependency(search);
    for (const resource of [`${helperName}:log-stream:*`, "aws/spans:*"])
      Validations.of(helperRole).acknowledge({
        id: `AwsSolutions::AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:logs:${this.region}:${this.account}:log-group:${resource}]`,
        reason:
          "The helper can set retention only on aws/spans and write operational logs only inside its own encrypted log group.",
      });
    new CfnOutput(this, "SpansLogGroup", { value: names[0] });
    new CfnOutput(this, "TraceKeyArn", { value: key.keyArn });
    new CfnOutput(this, "OtlpTracesEndpoint", {
      value: `https://xray.${this.region}.${this.urlSuffix}/v1/traces`,
    });
  }
}
