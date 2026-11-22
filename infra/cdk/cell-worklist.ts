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
  CfnApi,
  CfnAuthorizer,
  CfnIntegration,
  CfnRoute,
  CfnStage,
} from "aws-cdk-lib/aws-apigatewayv2";
import { SubnetType, Vpc } from "aws-cdk-lib/aws-ec2";
import { Key } from "aws-cdk-lib/aws-kms";
import { Code, Function, Runtime, Architecture } from "aws-cdk-lib/aws-lambda";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";
import {
  DatabaseCluster,
  DatabaseClusterEngine,
  AuroraPostgresEngineVersion,
  ClusterInstance,
  Credentials,
} from "aws-cdk-lib/aws-rds";
import { PolicyStatement, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { CfnPolicyStore, CfnPolicy } from "aws-cdk-lib/aws-verifiedpermissions";
import { Construct } from "constructs";
import { Secret } from "aws-cdk-lib/aws-secretsmanager";

interface WorklistProps extends StackProps {
  bundle: string;
  issuer: string;
  clientId: string;
  tenantId: string;
  fhir?: { endpoint: string; arn: string; expiresAt: string; keyArn: string };
  traceExport?: boolean;
  fhirExpiresAt?: string;
}

export class CellWorklist extends Stack {
  constructor(scope: Construct, id: string, props: WorklistProps) {
    super(scope, id, props);
    Tags.of(this).add("Project", "verimed");
    Tags.of(this).add("Tenant", "a");
    Tags.of(this).add("Env", "dev");
    const key = new Key(this, "DataKey", { enableKeyRotation: true });
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
          ArnLike: {
            "kms:EncryptionContext:aws:logs:arn": this.formatArn({
              service: "logs",
              resource: "log-group",
              resourceName: `${this.stackName}-*`,
              arnFormat: ArnFormat.COLON_RESOURCE_NAME,
            }),
          },
        },
      }),
    );
    const vpc = new Vpc(this, "DatabaseVpc", {
      maxAzs: 2,
      natGateways: 0,
      restrictDefaultSecurityGroup: true,
      subnetConfiguration: [
        { name: "data", subnetType: SubnetType.PRIVATE_ISOLATED },
      ],
    });
    const cluster = new DatabaseCluster(this, "Database", {
      engine: DatabaseClusterEngine.auroraPostgres({
        version: AuroraPostgresEngineVersion.of("17.11", "17"),
      }),
      writer: ClusterInstance.serverlessV2("writer", {
        publiclyAccessible: false,
      }),
      serverlessV2MinCapacity: 0,
      serverlessV2MaxCapacity: 1,
      serverlessV2AutoPauseDuration: Duration.minutes(5),
      enableDataApi: true,
      credentials: Credentials.fromGeneratedSecret("verimed_admin", {
        encryptionKey: key,
      }),
      defaultDatabaseName: "verimed",
      vpc,
      vpcSubnets: { subnetType: SubnetType.PRIVATE_ISOLATED },
      storageEncryptionKey: key,
      backup: { retention: Duration.days(7) },
      removalPolicy: RemovalPolicy.RETAIN,
      deletionProtection: true,
      cloudwatchLogsExports: ["postgresql"],
    });
    const store = new CfnPolicyStore(this, "Policies", {
      validationSettings: { mode: "STRICT" },
      schema: {
        cedarJson: JSON.stringify({
          VeriMed: {
            entityTypes: {
              User: {
                shape: {
                  type: "Record",
                  attributes: {
                    tenant: { type: "String", required: true },
                    roles: {
                      type: "Set",
                      element: { type: "String" },
                      required: true,
                    },
                  },
                },
              },
              Tenant: {
                shape: {
                  type: "Record",
                  attributes: { tenant: { type: "String", required: true } },
                },
              },
            },
            actions: {
              ListEncounters: {
                appliesTo: {
                  principalTypes: ["User"],
                  resourceTypes: ["Tenant"],
                  context: { type: "Record", attributes: {} },
                },
              },
              ListPatients: {
                appliesTo: {
                  principalTypes: ["User"],
                  resourceTypes: ["Tenant"],
                  context: { type: "Record", attributes: {} },
                },
              },
            },
          },
        }),
      },
    });
    const runtimeSecret = new Secret(this, "ReadOnlyCredentials", {
      encryptionKey: key,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ username: "verimed_reader" }),
        generateStringKey: "password",
        passwordLength: 48,
        excludePunctuation: true,
      },
    });
    const ledgerSecret = new Secret(this, "LedgerWriterCredentials", {
      encryptionKey: key,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          username: "verimed_ledger_writer",
        }),
        generateStringKey: "password",
        passwordLength: 48,
        excludePunctuation: true,
      },
    });
    Validations.of(ledgerSecret).acknowledge({
      id: "AwsSolutions::AwsSolutions-SMG4",
      reason:
        "Rotation is pending the CellData operations slice. This credential is restricted to ledger append/read and is not granted to the web API.",
    });
    Validations.of(runtimeSecret).acknowledge({
      id: "AwsSolutions::AwsSolutions-SMG4",
      reason:
        "Automatic rotation is pending the CellData operations slice. This generated dev credential has read-only database access.",
    });
    new CfnPolicy(this, "ReadWorklist", {
      policyStoreId: store.attrPolicyStoreId,
      definition: {
        static: {
          statement:
            'permit(principal is VeriMed::User, action == VeriMed::Action::"ListEncounters", resource is VeriMed::Tenant) when { principal.tenant == resource.tenant && principal.roles.containsAny(["PHYSICIAN", "PHARMACIST", "CODER", "AUDITOR", "TENANT_ADMIN"]) };',
        },
      },
    });
    new CfnPolicy(this, "ReadPatients", {
      policyStoreId: store.attrPolicyStoreId,
      definition: {
        static: {
          statement:
            'permit(principal is VeriMed::User, action == VeriMed::Action::"ListPatients", resource is VeriMed::Tenant) when { principal.tenant == resource.tenant && principal.roles.containsAny(["PHYSICIAN", "PHARMACIST", "CODER", "AUDITOR", "TENANT_ADMIN"]) };',
        },
      },
    });
    const apiLogs = new LogGroup(this, "ApiLogs", {
      retention: RetentionDays.ONE_MONTH,
      encryptionKey: key,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const api = new Function(this, "Api", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      code: Code.fromAsset(props.bundle),
      handler: "app.main.handler",
      memorySize: 256,
      timeout: Duration.seconds(60),
      logGroup: apiLogs,
      environment: {
        DATABASE_CLUSTER_ARN: cluster.clusterArn,
        DATABASE_SECRET_ARN: runtimeSecret.secretArn,
        POLICY_STORE_ID: store.attrPolicyStoreId,
        TENANT_ID: props.tenantId,
        COGNITO_CLIENT_ID: props.clientId,
        VERIMED_ENV: "dev",
        VERIMED_TRACE_EXPORTER: props.traceExport ? "aws" : "console",
        ...(props.fhir
          ? {
              FHIR_ENDPOINT: props.fhir.endpoint,
              FHIR_EXPIRES_AT: props.fhir.expiresAt,
            }
          : props.fhirExpiresAt
            ? { FHIR_EXPIRES_AT: props.fhirExpiresAt }
            : {}),
      },
    });
    if (props.traceExport)
      api.addToRolePolicy(
        new PolicyStatement({
          actions: ["xray:PutTraceSegments"],
          resources: ["*"],
        }),
      );
    if (props.traceExport)
      Validations.of(api.role!).acknowledge({
        id: "AwsSolutions::AwsSolutions-IAM5[Resource::*]",
        reason:
          "X-Ray PutTraceSegments does not support resource-level ARNs; this grant contains only that trace-ingestion action.",
      });
    if (props.fhir)
      api.addToRolePolicy(
        new PolicyStatement({
          actions: ["healthlake:SearchWithGet"],
          resources: [props.fhir.arn],
        }),
      );
    if (props.fhir)
      api.addToRolePolicy(
        new PolicyStatement({
          actions: ["kms:Decrypt", "kms:DescribeKey"],
          resources: [props.fhir.keyArn],
          conditions: {
            StringEquals: {
              "kms:ViaService": `healthlake.${this.region}.amazonaws.com`,
              "kms:CallerAccount": this.account,
            },
          },
        }),
      );
    runtimeSecret.grantRead(api);
    api.addToRolePolicy(
      new PolicyStatement({
        actions: [
          "rds-data:ExecuteStatement",
          "rds-data:BeginTransaction",
          "rds-data:CommitTransaction",
          "rds-data:RollbackTransaction",
        ],
        resources: [cluster.clusterArn],
      }),
    );
    api.addToRolePolicy(
      new PolicyStatement({
        actions: ["verifiedpermissions:IsAuthorized"],
        resources: [store.attrArn],
      }),
    );
    const http = new CfnApi(this, "Http", {
      name: "verimed-dev-worklist",
      protocolType: "HTTP",
      disableExecuteApiEndpoint: false,
    });
    const accessLogs = new LogGroup(this, "AccessLogs", {
      retention: RetentionDays.ONE_MONTH,
      encryptionKey: key,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const jwt = new CfnAuthorizer(this, "Jwt", {
      apiId: http.ref,
      authorizerType: "JWT",
      name: "CellCognito",
      identitySource: ["$request.header.Authorization"],
      jwtConfiguration: { issuer: props.issuer, audience: [props.clientId] },
    });
    const integration = new CfnIntegration(this, "Proxy", {
      apiId: http.ref,
      integrationType: "AWS_PROXY",
      integrationUri: api.functionArn,
      payloadFormatVersion: "2.0",
      timeoutInMillis: 30000,
    });
    for (const path of [
      "/v1/encounters",
      "/v1/patients",
      "/v1/health",
      "/v1/openapi.json",
    ]) {
      new CfnRoute(this, path.replaceAll("/", "_"), {
        apiId: http.ref,
        routeKey: `GET ${path}`,
        target: `integrations/${integration.ref}`,
        authorizationType: "JWT",
        authorizerId: jwt.ref,
      });
    }
    new CfnStage(this, "Stage", {
      apiId: http.ref,
      stageName: "$default",
      autoDeploy: true,
      accessLogSettings: {
        destinationArn: accessLogs.logGroupArn,
        format:
          '{"requestId":"$context.requestId","status":"$context.status","latency":"$context.responseLatency"}',
      },
      defaultRouteSettings: {
        throttlingBurstLimit: 10,
        throttlingRateLimit: 5,
      },
    });
    api.addPermission("GatewayInvoke", {
      principal: new ServicePrincipal("apigateway.amazonaws.com"),
      sourceArn: this.formatArn({
        service: "execute-api",
        resource: http.ref,
        resourceName: "*/GET/v1/*",
      }),
    });
    Validations.of(cluster.node.findChild("Secret")).acknowledge({
      id: "AwsSolutions::AwsSolutions-SMG4",
      reason:
        "Automatic secret rotation is pending the full CellData operations slice. The generated dev secret is never sent to the browser.",
    });
    Validations.of(api.role!).acknowledge({
      id: "AwsSolutions::AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole]",
      reason:
        "The Lambda execution role uses the AWS log delivery policy for this dev slice.",
    });
    for (const [target, rules, reason] of [
      [
        vpc,
        ["VPC7"],
        "The isolated dev database VPC has no workload ingress or internet egress. Foundation flow logs are separate. Add data-VPC flow logging before production.",
      ],
      [
        cluster,
        ["RDS6", "RDS10", "RDS11"],
        "The dev database uses a generated master secret for Data API and an explicit restricted role for each query. One auto-pausing writer controls dev cost.",
      ],
      [
        api,
        ["L1", "IAM4", "IAM5"],
        "Python 3.12 follows the project specification. Data API uses scoped database/secret access. Optional X-Ray PutTraceSegments does not support resource-level ARNs.",
      ],
    ] as const) {
      for (const rule of rules)
        Validations.of(target).acknowledge({
          id: `AwsSolutions::AwsSolutions-${rule}`,
          reason,
        });
    }
    new CfnOutput(this, "ApiUrl", {
      value: `https://${http.ref}.execute-api.${this.region}.${this.urlSuffix}/v1`,
    });
    new CfnOutput(this, "ApiFunctionName", { value: api.functionName });
    new CfnOutput(this, "ClusterArn", { value: cluster.clusterArn });
    new CfnOutput(this, "SecretArn", { value: cluster.secret!.secretArn });
    new CfnOutput(this, "RuntimeSecretArn", { value: runtimeSecret.secretArn });
    new CfnOutput(this, "LedgerWriterSecretArn", {
      value: ledgerSecret.secretArn,
    });
    new CfnOutput(this, "PolicyStoreId", { value: store.attrPolicyStoreId });
  }
}
