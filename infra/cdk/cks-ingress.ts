import { Construct } from "constructs";
import {
  ArnFormat,
  Duration,
  RemovalPolicy,
  Stack,
  Tags,
  Validations,
} from "aws-cdk-lib";
import {
  AccessLogFormat,
  AuthorizationType,
  EndpointType,
  LambdaIntegration,
  LogGroupLogDestination,
  MethodLoggingLevel,
  RestApi,
} from "aws-cdk-lib/aws-apigateway";
import {
  AnyPrincipal,
  ArnPrincipal,
  Effect,
  PolicyDocument,
  PolicyStatement,
  ServicePrincipal,
} from "aws-cdk-lib/aws-iam";
import { IFunction } from "aws-cdk-lib/aws-lambda";
import { Key } from "aws-cdk-lib/aws-kms";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";

export interface CksCaller {
  roleArn: string;
  tenantId: string;
  endpointIds: string[];
  operations: ("normalize" | "classes" | "labels")[];
}

export interface CksIngressProps {
  handler: IFunction;
  stage: string;
  callers: CksCaller[];
}

/** Private ingress only. Runtime, cache, outbound reference fetching and endpoint stacks are separate. */
export class CksIngress extends Construct {
  readonly api: RestApi;
  readonly runtimeEnvironment: Record<string, string>;
  constructor(scope: Construct, id: string, props: CksIngressProps) {
    super(scope, id);
    Tags.of(this).add("Project", "verimed");
    Tags.of(this).add("Tenant", "hub");
    Tags.of(this).add("Env", props.stage);
    if (!/^[a-zA-Z0-9_-]+$/.test(props.stage) || !props.callers.length)
      throw new Error("CKS stage and explicit caller bindings are required");
    const seen = new Set<string>();
    for (const caller of props.callers) {
      if (
        !/^arn:aws:iam::[0-9]{12}:role\/[A-Za-z0-9+=,.@_/-]+$/.test(
          caller.roleArn,
        ) ||
        !/^[0-9a-f-]{36}$/i.test(caller.tenantId) ||
        !caller.endpointIds.length ||
        caller.endpointIds.some((v) => !/^vpce-[0-9a-f]+$/.test(v)) ||
        !caller.operations.length ||
        caller.operations.some(
          (v) => !["normalize", "classes", "labels"].includes(v),
        ) ||
        seen.has(caller.roleArn)
      )
        throw new Error("Invalid or duplicate CKS caller binding");
      seen.add(caller.roleArn);
    }
    const stack = Stack.of(this);
    const key = new Key(this, "LogKey", { enableKeyRotation: true });
    key.addToResourcePolicy(
      new PolicyStatement({
        principals: [
          new ServicePrincipal("logs." + stack.region + "." + stack.urlSuffix),
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
            "kms:EncryptionContext:aws:logs:arn": stack.formatArn({
              service: "logs",
              resource: "log-group",
              resourceName: "*",
              arnFormat: ArnFormat.COLON_RESOURCE_NAME,
            }),
          },
        },
      }),
    );
    const access = new LogGroup(this, "AccessLogs", {
      encryptionKey: key,
      retention: RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const endpoints = [...new Set(props.callers.flatMap((v) => v.endpointIds))];
    const policy = new PolicyDocument({
      statements: [
        new PolicyStatement({
          effect: Effect.DENY,
          principals: [new AnyPrincipal()],
          actions: ["execute-api:Invoke"],
          resources: ["execute-api:/*"],
          conditions: { StringNotEquals: { "aws:SourceVpce": endpoints } },
        }),
        new PolicyStatement({
          effect: Effect.DENY,
          principals: [new AnyPrincipal()],
          actions: ["execute-api:Invoke"],
          resources: ["execute-api:/*"],
          conditions: { ArnNotEquals: { "aws:PrincipalArn": [...seen] } },
        }),
        ...props.callers.map(
          (caller) =>
            new PolicyStatement({
              principals: [new ArnPrincipal(caller.roleArn)],
              actions: ["execute-api:Invoke"],
              resources: caller.operations.map(
                (op) => "execute-api:/" + props.stage + "/POST/" + op,
              ),
              conditions: {
                StringEquals: { "aws:SourceVpce": caller.endpointIds },
              },
            }),
        ),
      ],
    });
    this.api = new RestApi(this, "Api", {
      endpointConfiguration: { types: [EndpointType.PRIVATE] },
      policy,
      cloudWatchRole: true,
      deployOptions: {
        stageName: props.stage,
        accessLogDestination: new LogGroupLogDestination(access),
        accessLogFormat: AccessLogFormat.custom(
          JSON.stringify({
            requestId: "$context.extendedRequestId",
            status: "$context.status",
            latency: "$context.responseLatency",
          }),
        ),
        dataTraceEnabled: false,
        loggingLevel: MethodLoggingLevel.ERROR,
        tracingEnabled: true,
        metricsEnabled: true,
        throttlingRateLimit: 2,
        throttlingBurstLimit: 4,
        cacheClusterEnabled: false,
      },
    });
    this.runtimeEnvironment = {
      CKS_API_ID: this.api.restApiId,
      CKS_HUB_ACCOUNT_ID: stack.account,
      CKS_STAGE: props.stage,
      CKS_CALLERS_JSON: JSON.stringify(
        props.callers.map((caller) => ({
          role_arn: caller.roleArn,
          tenant_id: caller.tenantId,
          endpoint_ids: caller.endpointIds,
          operations: caller.operations,
        })),
      ),
    };
    Validations.of(this.api.node.findChild("CloudWatchRole")).acknowledge({
      id: "AwsSolutions::AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs]",
      reason:
        "API Gateway uses its AWS-managed log-delivery policy. Access logs contain only generated request IDs, status and latency; request payload logging is disabled.",
    });
    for (const op of ["normalize", "classes", "labels"]) {
      this.api.root.addResource(op).addMethod(
        "POST",
        new LambdaIntegration(props.handler, {
          proxy: true,
          allowTestInvoke: false,
          timeout: Duration.seconds(25),
        }),
        { authorizationType: AuthorizationType.IAM },
      );
    }
    for (const [rule, reason] of [
      [
        "APIG2",
        "Strict backend Pydantic schemas enforce drug-only payloads and emit redacted validation errors; gateway payload logging is disabled.",
      ],
      [
        "APIG3",
        "This internal API is private and restricted to explicit cell roles and endpoint IDs. Production WAF/rate-limit hardening remains a deployment acceptance gate.",
      ],
      [
        "COG4",
        "Every method uses AWS_IAM service authentication, not end-user Cognito authentication.",
      ],
    ] as const)
      Validations.of(this.api).acknowledge({
        id: "AwsSolutions::AwsSolutions-" + rule,
        reason,
      });
  }
}
