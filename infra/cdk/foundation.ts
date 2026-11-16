import {
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
} from "aws-cdk-lib";
import { CfnBudget } from "aws-cdk-lib/aws-budgets";
import {
  Alarm,
  ComparisonOperator,
  TreatMissingData,
} from "aws-cdk-lib/aws-cloudwatch";
import {
  FlowLogDestination,
  GatewayVpcEndpointAwsService,
  InterfaceVpcEndpointAwsService,
  SecurityGroup,
  SubnetType,
  Vpc,
} from "aws-cdk-lib/aws-ec2";
import { PolicyStatement, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { Key } from "aws-cdk-lib/aws-kms";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";
import { Topic } from "aws-cdk-lib/aws-sns";
import { SnsAction } from "aws-cdk-lib/aws-cloudwatch-actions";
import { Construct } from "constructs";

export interface FoundationProps extends StackProps {
  stage: string;
  tenant: string;
}

export class Foundation extends Stack {
  constructor(scope: Construct, id: string, props: FoundationProps) {
    super(scope, id, props);
    Tags.of(this).add("Project", "verimed");
    Tags.of(this).add("Env", props.stage);
    Tags.of(this).add("Tenant", props.tenant);
    const key = new Key(this, "Key", { enableKeyRotation: true });
    const logs = new LogGroup(this, "VpcFlowLogs", {
      encryptionKey: key,
      retention: RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const vpc = new Vpc(this, "Vpc", {
      maxAzs: 2,
      natGateways: 0,
      restrictDefaultSecurityGroup: true,
      subnetConfiguration: [
        { name: "isolated", subnetType: SubnetType.PRIVATE_ISOLATED },
      ],
      flowLogs: {
        All: { destination: FlowLogDestination.toCloudWatchLogs(logs) },
      },
    });
    vpc.addGatewayEndpoint("S3", { service: GatewayVpcEndpointAwsService.S3 });
    const endpoints = {
      Bedrock: InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
      Ecr: InterfaceVpcEndpointAwsService.ECR,
      EcrDocker: InterfaceVpcEndpointAwsService.ECR_DOCKER,
      Logs: InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
      Sts: InterfaceVpcEndpointAwsService.STS,
      Secrets: InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
      Sqs: InterfaceVpcEndpointAwsService.SQS,
      Kms: InterfaceVpcEndpointAwsService.KMS,
      States: InterfaceVpcEndpointAwsService.STEP_FUNCTIONS,
    };
    const endpointSecurityGroup = new SecurityGroup(
      this,
      "EndpointSecurityGroup",
      {
        vpc,
        allowAllOutbound: false,
        description:
          "Permit explicitly authorized workload security groups to reach VPC endpoints",
      },
    );
    for (const [name, service] of Object.entries(endpoints)) {
      vpc.addInterfaceEndpoint(name, {
        service,
        open: false,
        securityGroups: [endpointSecurityGroup],
      });
    }
    new CfnOutput(this, "EndpointSecurityGroupId", {
      value: endpointSecurityGroup.securityGroupId,
    });
    const alerts = new Topic(this, "Alerts", {
      masterKey: key,
      enforceSSL: true,
    });
    const noFlowLogs = new Alarm(this, "NoFlowLogs", {
      metric: logs.metricIncomingLogEvents({ period: Duration.hours(1) }),
      threshold: 1,
      evaluationPeriods: 2,
      comparisonOperator: ComparisonOperator.LESS_THAN_THRESHOLD,
      treatMissingData: TreatMissingData.NOT_BREACHING,
    });
    noFlowLogs.addAlarmAction(new SnsAction(alerts));
    new CfnBudget(this, "MonthlyBudget", {
      budget: {
        budgetName: `verimed-${props.stage}-${props.tenant}`,
        budgetLimit: { amount: 100, unit: "USD" },
        budgetType: "COST",
        timeUnit: "MONTHLY",
      },
      notificationsWithSubscribers: [
        {
          notification: {
            comparisonOperator: "GREATER_THAN",
            notificationType: "ACTUAL",
            threshold: 80,
          },
          subscribers: [{ address: alerts.topicArn, subscriptionType: "SNS" }],
        },
      ],
    });
    alerts.addToResourcePolicy(
      new PolicyStatement({
        principals: [new ServicePrincipal("budgets.amazonaws.com")],
        actions: ["sns:Publish"],
        resources: [alerts.topicArn],
        conditions: { StringEquals: { "aws:SourceAccount": this.account } },
      }),
    );
    key.grant(
      new ServicePrincipal("budgets.amazonaws.com"),
      "kms:Decrypt",
      "kms:GenerateDataKey",
    );
    key.grant(
      new ServicePrincipal("cloudwatch.amazonaws.com"),
      "kms:Decrypt",
      "kms:GenerateDataKey",
    );
  }
}

export class HubFoundation extends Foundation {}
export class CellFoundation extends Foundation {}
