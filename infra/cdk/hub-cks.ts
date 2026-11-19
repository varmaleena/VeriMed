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
import {
  FlowLogDestination,
  InterfaceVpcEndpointAwsService,
  Port,
  SecurityGroup,
  SubnetType,
  Vpc,
} from "aws-cdk-lib/aws-ec2";
import {
  CfnServerlessCache,
  CfnUser,
  CfnUserGroup,
} from "aws-cdk-lib/aws-elasticache";
import {
  ArnPrincipal,
  PolicyStatement,
  Role,
  ServicePrincipal,
} from "aws-cdk-lib/aws-iam";
import { Key } from "aws-cdk-lib/aws-kms";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";
import { Secret } from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";
import { CksCaller, CksIngress } from "./cks-ingress";

export interface HubCksProps extends StackProps {
  bundle: string;
  stage: string;
  callers: CksCaller[];
  cacheMajorVersion: string;
}

/** Isolated API/cache + IAM-only non-VPC reference worker. No NAT and no public API. */
export class HubCKS extends Stack {
  constructor(scope: Construct, id: string, props: HubCksProps) {
    super(scope, id, props);
    if (!/^[a-z][a-z0-9-]{0,15}$/.test(props.stage))
      throw new Error("CKS stage must be a short lowercase deployment name");
    Tags.of(this).add("Project", "verimed");
    Tags.of(this).add("Tenant", "hub");
    Tags.of(this).add("Env", props.stage);
    if (!/^[0-9]+$/.test(props.cacheMajorVersion))
      throw new Error("A catalog-verified cache major version is required");
    const key = new Key(this, "Key", {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    key.addToResourcePolicy(
      new PolicyStatement({
        principals: [
          new ServicePrincipal("logs." + this.region + "." + this.urlSuffix),
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
          ArnLike: {
            "kms:EncryptionContext:aws:logs:arn": this.formatArn({
              service: "logs",
              resource: "log-group",
              resourceName: "*",
              arnFormat: ArnFormat.COLON_RESOURCE_NAME,
            }),
          },
        },
      }),
    );
    const log = (name: string): LogGroup =>
      new LogGroup(this, name, {
        encryptionKey: key,
        retention: RetentionDays.ONE_MONTH,
        removalPolicy: RemovalPolicy.RETAIN,
      });
    const flowLogs = log("FlowLogs");
    const vpc = new Vpc(this, "Vpc", {
      maxAzs: 2,
      natGateways: 0,
      restrictDefaultSecurityGroup: true,
      subnetConfiguration: [
        { name: "isolated", subnetType: SubnetType.PRIVATE_ISOLATED },
      ],
      flowLogs: {
        All: { destination: FlowLogDestination.toCloudWatchLogs(flowLogs) },
      },
    });
    const apiSg = new SecurityGroup(this, "ApiSecurityGroup", {
      vpc,
      allowAllOutbound: false,
    });
    const cacheSg = new SecurityGroup(this, "CacheSecurityGroup", {
      vpc,
      allowAllOutbound: false,
    });
    const endpointSg = new SecurityGroup(this, "EndpointSecurityGroup", {
      vpc,
      allowAllOutbound: false,
    });
    cacheSg.addIngressRule(
      apiSg,
      Port.tcp(6379),
      "Only private CKS cache commands",
    );
    endpointSg.addIngressRule(
      apiSg,
      Port.tcp(443),
      "Only private CKS AWS calls",
    );
    apiSg.addEgressRule(cacheSg, Port.tcp(6379));
    apiSg.addEgressRule(endpointSg, Port.tcp(443));

    const credential = new Secret(this, "CacheCredential", {
      encryptionKey: key,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ username: "cks" }),
        generateStringKey: "password",
        passwordLength: 48,
        excludePunctuation: true,
      },
    });
    const user = new CfnUser(this, "CacheUser", {
      engine: "valkey",
      userId: "verimed-cks-" + props.stage,
      userName: "cks",
      authenticationMode: {
        Type: "password",
        Passwords: [credential.secretValueFromJson("password").unsafeUnwrap()],
      },
      accessString:
        "on ~cks:* -@all +get +set +ping +hello +client|setinfo +client|setname",
    });
    const group = new CfnUserGroup(this, "CacheUsers", {
      engine: "valkey",
      userGroupId: "verimed-cks-" + props.stage,
      userIds: [user.ref],
    });
    const cache = new CfnServerlessCache(this, "Cache", {
      engine: "valkey",
      majorEngineVersion: props.cacheMajorVersion,
      serverlessCacheName: "verimed-cks-" + props.stage,
      kmsKeyId: key.keyArn,
      userGroupId: group.ref,
      securityGroupIds: [cacheSg.securityGroupId],
      subnetIds: vpc.isolatedSubnets.map((s) => s.subnetId),
      cacheUsageLimits: {
        dataStorage: { maximum: 1, unit: "GB" },
        ecpuPerSecond: { maximum: 1000 },
      },
    });
    const collectorLogs = log("ReferenceWorkerLogs");
    const collectorRole = new Role(this, "ReferenceWorkerRole", {
      assumedBy: new ServicePrincipal("lambda.amazonaws.com"),
    });
    collectorLogs.grantWrite(collectorRole);
    const worker = new Function(this, "ReferenceWorker", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.X86_64,
      handler: "cks.bridge.handler",
      code: Code.fromAsset(props.bundle),
      memorySize: 256,
      timeout: Duration.seconds(18),
      logGroup: collectorLogs,
      role: collectorRole,
    });
    const apiLogs = log("ApiLogs");
    const apiRole = new Role(this, "ApiRole", {
      assumedBy: new ServicePrincipal("lambda.amazonaws.com"),
    });
    apiLogs.grantWrite(apiRole);
    apiRole.addToPolicy(
      new PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        resources: [credential.secretArn],
      }),
    );
    apiRole.addToPolicy(
      new PolicyStatement({
        actions: ["kms:Decrypt"],
        resources: [key.keyArn],
        conditions: {
          StringEquals: {
            "kms:ViaService":
              "secretsmanager." + this.region + "." + this.urlSuffix,
            "kms:EncryptionContext:SecretARN": credential.secretArn,
          },
        },
      }),
    );
    const api = new Function(this, "ApiRuntime", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.X86_64,
      handler: "cks.service.handler",
      code: Code.fromAsset(props.bundle),
      memorySize: 256,
      timeout: Duration.seconds(25),
      logGroup: apiLogs,
      role: apiRole,
      vpc,
      vpcSubnets: { subnetType: SubnetType.PRIVATE_ISOLATED },
      securityGroups: [apiSg],
      environment: {
        CKS_PRIVATE_MODE: "true",
        CKS_REFERENCE_WORKER_ARN: worker.functionArn,
        CKS_CACHE_SECRET_ARN: credential.secretArn,
        CKS_CACHE_HOST: cache.attrEndpointAddress,
      },
    });
    apiRole.addToPolicy(
      new PolicyStatement({
        actions: ["lambda:InvokeFunction"],
        resources: [worker.functionArn],
      }),
    );
    for (const [name, service, actions, resources] of [
      [
        "Lambda",
        InterfaceVpcEndpointAwsService.LAMBDA,
        ["lambda:InvokeFunction"],
        [worker.functionArn],
      ],
      [
        "Secrets",
        InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
        ["secretsmanager:GetSecretValue"],
        [credential.secretArn],
      ],
    ] as const) {
      const endpoint = vpc.addInterfaceEndpoint(name, {
        service,
        privateDnsEnabled: true,
        open: false,
        securityGroups: [endpointSg],
        subnets: { subnets: [vpc.isolatedSubnets[0]] },
      });
      endpoint.addToPolicy(
        new PolicyStatement({
          principals: [new ArnPrincipal(apiRole.roleArn)],
          actions: [...actions],
          resources: [...resources],
        }),
      );
    }
    const ingress = new CksIngress(this, "Ingress", {
      handler: api,
      stage: props.stage,
      callers: props.callers,
    });
    for (const [name, value] of Object.entries(ingress.runtimeEnvironment))
      api.addEnvironment(name, value);
    for (const target of [worker, api])
      Validations.of(target).acknowledge({
        id: "AwsSolutions::AwsSolutions-L1",
        reason:
          "Python 3.12 is the explicit project runtime and is supported by Lambda.",
      });
    Validations.of(apiRole).acknowledge({
      id: "AwsSolutions::AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole]",
      reason:
        "Lambda requires ENI provisioning for its isolated VPC attachment; the role has no general internet ingress or egress.",
    });
    for (const target of [apiRole, collectorRole])
      Validations.of(target).acknowledge({
        id: "AwsSolutions::AwsSolutions-IAM5",
        reason:
          "Log writes require the generated log group's stream ARN suffix; VPC ENI operations require dynamic resources. Worker invocation and secret reads are explicitly scoped.",
      });
    Validations.of(credential).acknowledge({
      id: "AwsSolutions::AwsSolutions-SMG4",
      reason:
        "Dev cache credential rotation needs coordinated ElastiCache user update; implement rotation before production. Credentials are generated, KMS encrypted and fetched at runtime.",
    });
    new CfnOutput(this, "ApiId", { value: ingress.api.restApiId });
    new CfnOutput(this, "ApiUrl", { value: ingress.api.url });
    new CfnOutput(this, "ReferenceWorkerArn", { value: worker.functionArn });
    new CfnOutput(this, "ApiRuntimeArn", { value: api.functionArn });
    new CfnOutput(this, "CacheEndpoint", { value: cache.attrEndpointAddress });
  }
}
