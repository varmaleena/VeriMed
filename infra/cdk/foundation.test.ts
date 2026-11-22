import { test } from "node:test";
import { ok } from "node:assert/strict";
import { App, Stack, Validations } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
import { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { CksIngress } from "./cks-ingress";
import { HubCKS } from "./hub-cks";
import { Match, Template } from "aws-cdk-lib/assertions";
import { CellFoundation, HubFoundation } from "./foundation";
import { CellIdentity } from "./cell-identity";
import { CellWorklist } from "./cell-worklist";
import { CellFhirDemo } from "./cell-fhir-demo";
import { CellFhirImport } from "./cell-fhir-import";
import { CellSynthea } from "./cell-synthea";
import { CellObservability } from "./cell-observability";
import { SPAN_RETENTION_HANDLER } from "./span-retention-handler";
import { runInNewContext } from "node:vm";
import { Bucket } from "aws-cdk-lib/aws-s3";
import { Key } from "aws-cdk-lib/aws-kms";
import { CellLedger } from "./cell-ledger";

test("Trace retention helper rejects other groups and never logs signed CFN callbacks", async () => {
  const writes: unknown[] = [];
  const replies: Record<string, unknown>[] = [];
  const logs: string[] = [];
  const exported: { handler?: (event: unknown) => Promise<void> } = {};
  class Command {
    constructor(public readonly input: unknown) {}
  }
  class Client {
    async send(command: Command) {
      writes.push(command.input);
    }
  }
  runInNewContext(SPAN_RETENTION_HANDLER, {
    exports: exported,
    require: () => ({
      CloudWatchLogsClient: Client,
      PutRetentionPolicyCommand: Command,
    }),
    URL,
    AbortSignal,
    Buffer,
    console: { error: (value: string) => logs.push(value) },
    fetch: async (_url: URL, options: { body: string }) => {
      replies.push(JSON.parse(options.body));
      return { ok: true };
    },
  });
  const base = {
    RequestType: "Create",
    ResponseURL:
      "https://cloudformation-custom-resource-response-useast1.s3.amazonaws.com/unit?X-Amz-Signature=unit-private-marker",
    StackId: "unit",
    RequestId: "unit",
    LogicalResourceId: "unit",
  };
  await exported.handler!({
    ...base,
    ResourceProperties: { LogGroupName: "aws/spans", RetentionInDays: 30 },
  });
  await exported.handler!({
    ...base,
    ResourceProperties: { LogGroupName: "another-tenant", RetentionInDays: 30 },
  });
  ok(
    writes.length === 1 &&
      replies[0].Status === "SUCCESS" &&
      replies[1].Status === "FAILED",
  );
  ok(replies.every((reply) => reply.NoEcho === true));
  ok(!JSON.stringify(logs).includes("unit-private-marker"));
});

test("CellObservability owns encrypted retained trace storage and account-scoped X-Ray delivery", () => {
  const app = new App();
  const stack = new CellObservability(app, "Observability", {
    stage: "dev",
    tenant: "a",
    env: { account: "111111111111", region: "us-east-1" },
  });
  Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
  const template = Template.fromStack(stack);
  template.resourceCountIs("AWS::EC2::NatGateway", 0);
  template.resourceCountIs("AWS::EC2::VPCEndpoint", 0);
  template.hasResourceProperties("AWS::XRay::TransactionSearchConfig", {
    IndexingPercentage: 1,
    CloudWatchLogsConfiguration: { SpansLogGroupKmsKeyId: Match.anyValue() },
  });
  template.hasResourceProperties("AWS::Logs::LogGroup", {
    LogGroupName: "/aws/application-signals/data",
    KmsKeyId: Match.anyValue(),
    RetentionInDays: 30,
  });
  const policy = Object.values(
    template.findResources("AWS::Logs::ResourcePolicy"),
  )[0].Properties.PolicyDocument;
  ok(
    JSON.stringify(policy).includes("aws:SourceAccount") &&
      JSON.stringify(policy).includes("aws:SourceArn"),
  );
  app.synth();
});

test("Synthea uses a bounded on-demand private task and immutable image", () => {
  const app = new App();
  const env = { account: "111111111111", region: "us-east-1" };
  const foundation = new CellFoundation(app, "TaskFoundation", {
    stage: "dev",
    tenant: "a",
    env,
  });
  const stack = new CellSynthea(app, "Generation", {
    env,
    stage: "dev",
    tenant: "a",
    vpc: foundation.vpc,
    endpointSecurityGroup: foundation.endpointSecurityGroup,
    s3PrefixListId: "pl-01234567",
    transferBucket: Bucket.fromBucketName(
      foundation,
      "Transfer",
      "unit-only-bucket",
    ),
    transferKey: Key.fromKeyArn(
      foundation,
      "TransferKey",
      "arn:aws:kms:us-east-1:111111111111:key/00000000-0000-0000-0000-000000000001",
    ),
    imageDigest: `sha256:${"a".repeat(64)}`,
    buildContext: __dirname,
  });
  Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
  const template = Template.fromStack(stack);
  template.resourceCountIs("AWS::ECS::Service", 0);
  template.resourceCountIs("AWS::EC2::NatGateway", 0);
  template.hasResourceProperties("AWS::CodeBuild::Project", {
    TimeoutInMinutes: 25,
    ConcurrentBuildLimit: 1,
    Environment: Match.objectLike({
      Type: "ARM_CONTAINER",
      PrivilegedMode: true,
      ComputeType: "BUILD_GENERAL1_SMALL",
    }),
  });
  template.hasResourceProperties("AWS::ECR::Repository", {
    ImageTagMutability: "IMMUTABLE",
    ImageScanningConfiguration: { ScanOnPush: true },
  });
  template.hasResourceProperties("AWS::ECS::TaskDefinition", {
    Cpu: "1024",
    Memory: "2048",
    RuntimePlatform: {
      CpuArchitecture: "ARM64",
      OperatingSystemFamily: "LINUX",
    },
    ContainerDefinitions: Match.arrayWith([
      Match.objectLike({ User: "10001:10001", ReadonlyRootFilesystem: true }),
    ]),
  });
  template.hasResourceProperties("AWS::StepFunctions::StateMachine", {
    LoggingConfiguration: Match.objectLike({ IncludeExecutionData: false }),
    TracingConfiguration: { Enabled: true },
  });
  const policies = Object.values(template.findResources("AWS::IAM::Policy"));
  const statements = policies.flatMap(
    (policy) => policy.Properties.PolicyDocument.Statement,
  );
  const actionList = (statement: { Action: string | string[] }) =>
    Array.isArray(statement.Action) ? statement.Action : [statement.Action];
  const launches = statements.filter((statement) =>
    actionList(statement).includes("ecs:RunTask"),
  );
  ok(
    launches.length === 1 &&
      !JSON.stringify(launches[0].Resource).includes("*"),
  );
  ok(launches[0].Condition.ArnEquals["ecs:cluster"]);
  const writes = statements.filter((statement) =>
    actionList(statement).includes("s3:PutObject"),
  );
  ok(writes.length === 1);
  ok(JSON.stringify(writes[0].Resource).includes("unit-only-bucket/imports/"));
  ok(
    !statements.some((statement) =>
      actionList(statement).some((action) =>
        [
          "s3:*",
          "s3:DeleteObject",
          "healthlake:*",
          "secretsmanager:GetSecretValue",
        ].includes(action),
      ),
    ),
  );
  app.synth();
});

for (const StackType of [HubFoundation, CellFoundation]) {
  test(`${StackType.name} uses isolated networking and encrypted flow logs`, () => {
    const template = Template.fromStack(
      new StackType(new App(), "Foundation", { stage: "dev", tenant: "test" }),
    );
    template.resourceCountIs("AWS::EC2::NatGateway", 0);
    template.resourceCountIs("AWS::EC2::VPCEndpoint", 10);
    template.resourceCountIs("AWS::EC2::Subnet", 1);
    template.hasResourceProperties("AWS::KMS::Key", {
      EnableKeyRotation: true,
      KeyPolicy: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Principal: { Service: Match.anyValue() },
            Condition: {
              ArnEquals: {
                "kms:EncryptionContext:aws:logs:arn": Match.anyValue(),
              },
            },
          }),
        ]),
      },
    });
    template.resourceCountIs("AWS::EC2::FlowLog", 1);
    template.resourceCountIs("AWS::Budgets::Budget", 1);
  });
}

test("CellIdentity requires TOTP and permits only the authorization code flow", () => {
  const template = Template.fromStack(
    new CellIdentity(new App(), "Identity", {}),
  );
  template.hasResourceProperties("AWS::Cognito::UserPool", {
    MfaConfiguration: "ON",
    EnabledMfas: ["SOFTWARE_TOKEN_MFA"],
    AdminCreateUserConfig: { AllowAdminCreateUserOnly: true },
  });
  template.hasResourceProperties("AWS::Cognito::UserPoolClient", {
    AllowedOAuthFlows: ["code"],
    GenerateSecret: true,
    EnableTokenRevocation: true,
    CallbackURLs: ["http://localhost:3000/api/auth/callback/cognito"],
  });
});

test("CellIdentity disables MFA only for the explicit demo configuration", () => {
  const template = Template.fromStack(
    new CellIdentity(new App(), "DemoIdentity", { demoWithoutMfa: true }),
  );
  template.hasResourceProperties("AWS::Cognito::UserPool", {
    MfaConfiguration: "OFF",
  });
});

test("Worklist database is private, encrypted and can auto-pause, and routes require JWT", () => {
  const template = Template.fromStack(
    new CellWorklist(new App(), "Worklist", {
      bundle: __dirname,
      issuer: "https://example.invalid",
      clientId: "test-client",
      tenantId: "fe54cd8b-3dac-43d3-9a30-1f588cb60d35",
      traceExport: true,
      fhirExpiresAt: "2020-01-01T00:00:00Z",
    }),
  );
  template.resourceCountIs("AWS::EC2::NatGateway", 0);
  template.hasResourceProperties("AWS::Lambda::Function", {
    Handler: "app.main.handler",
    Environment: {
      Variables: Match.objectLike({
        VERIMED_TRACE_EXPORTER: "aws",
        FHIR_EXPIRES_AT: "2020-01-01T00:00:00Z",
        FHIR_ENDPOINT: Match.absent(),
      }),
    },
  });
  template.hasResourceProperties("AWS::RDS::DBCluster", {
    StorageEncrypted: true,
    EnableHttpEndpoint: true,
    ServerlessV2ScalingConfiguration: {
      MinCapacity: 0,
      MaxCapacity: 1,
      SecondsUntilAutoPause: 300,
    },
  });
  template.hasResourceProperties("AWS::RDS::DBInstance", {
    PubliclyAccessible: false,
  });
  template.hasResourceProperties("AWS::ApiGatewayV2::Route", {
    RouteKey: "GET /v1/encounters",
    AuthorizationType: "JWT",
  });
  template.hasResourceProperties("AWS::SecretsManager::Secret", {
    KmsKeyId: Match.anyValue(),
    GenerateSecretString: Match.objectLike({
      SecretStringTemplate: JSON.stringify({
        username: "verimed_ledger_writer",
      }),
    }),
  });
  for (const policy of Object.values(
    template.findResources("AWS::IAM::Policy"),
  )) {
    ok(
      !JSON.stringify(policy).includes("LedgerWriterCredentials"),
      "The web API must not receive the ledger writer secret",
    );
  }
});

test("FHIR demo uses encrypted synthetic preload and schedules only its own stack for teardown", () => {
  const template = Template.fromStack(
    new CellFhirDemo(new App(), "FhirDemo", {
      expiresAt: "2099-01-01T00:00:00Z",
    }),
  );
  template.hasResourceProperties("AWS::HealthLake::FHIRDatastore", {
    PreloadDataConfig: { PreloadDataType: "SYNTHEA" },
    NlpConfiguration: { Status: "DISABLED" },
    SseConfiguration: {
      KmsEncryptionConfig: {
        CmkType: "CUSTOMER_MANAGED_KMS_KEY",
        KmsKeyId: Match.anyValue(),
      },
    },
  });
  template.hasResourceProperties("AWS::Scheduler::Schedule", {
    ScheduleExpression: "at(2099-01-01T00:00:00)",
    ScheduleExpressionTimezone: "UTC",
    Target: Match.objectLike({
      Arn: "arn:aws:scheduler:::aws-sdk:cloudformation:deleteStack",
    }),
  });
  template.hasResourceProperties("AWS::IAM::Policy", {
    PolicyDocument: {
      Statement: Match.arrayWith([
        Match.objectLike({
          Action: "cloudformation:DeleteStack",
          Resource: { Ref: "AWS::StackId" },
        }),
      ]),
    },
  });
});

test("CellLedger retains an asymmetric signing key with cell tags", () => {
  const template = Template.fromStack(
    new CellLedger(new App(), "Ledger", { stage: "dev", tenant: "a" }),
  );
  template.hasResource("AWS::KMS::Key", {
    Properties: Match.objectLike({
      KeySpec: "ECC_NIST_P256",
      KeyUsage: "SIGN_VERIFY",
      Tags: Match.arrayWith([
        { Key: "Env", Value: "dev" },
        { Key: "Project", Value: "verimed" },
        { Key: "Tenant", Value: "a" },
      ]),
    }),
    DeletionPolicy: "Retain",
    UpdateReplacePolicy: "Retain",
  });
  template.resourceCountIs("AWS::EC2::NatGateway", 0);
});

test("Ledger anchors enforce seven-year compliance retention and conditional writes", () => {
  const template = Template.fromStack(
    new CellLedger(new App(), "LedgerAnchors", { stage: "dev", tenant: "a" }),
  );
  template.hasResource("AWS::S3::Bucket", {
    Properties: Match.objectLike({
      VersioningConfiguration: { Status: "Enabled" },
      ObjectLockEnabled: true,
      ObjectLockConfiguration: {
        ObjectLockEnabled: "Enabled",
        Rule: { DefaultRetention: { Mode: "COMPLIANCE", Years: 7 } },
      },
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [
          {
            BucketKeyEnabled: true,
            ServerSideEncryptionByDefault: {
              SSEAlgorithm: "aws:kms",
              KMSMasterKeyID: Match.anyValue(),
            },
          },
        ],
      },
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
      LoggingConfiguration: Match.anyValue(),
    }),
    DeletionPolicy: "Retain",
    UpdateReplacePolicy: "Retain",
  });
  template.hasResourceProperties("AWS::S3::BucketPolicy", {
    PolicyDocument: {
      Statement: Match.arrayWith([
        Match.objectLike({ Action: "s3:DeleteObject", Effect: "Deny" }),
        Match.objectLike({
          Action: "s3:PutObject",
          Effect: "Deny",
          Condition: { Null: { "s3:if-none-match": "true" } },
        }),
      ]),
    },
  });
});

test("Daily anchor worker has bounded retries and cannot access writer credentials", () => {
  const readerArn =
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:ci-reader-ABCDEF";
  const template = Template.fromStack(
    new CellLedger(new App(), "ScheduledLedger", {
      stage: "dev",
      tenant: "a",
      env: { account: "123456789012", region: "us-east-1" },
      worker: {
        bundle: __dirname,
        tenantId: "00000000-0000-0000-0000-000000000001",
        clusterArn: "arn:aws:rds:us-east-1:123456789012:cluster:ci-only",
        readerSecretArn: readerArn,
        databaseKeyArn:
          "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000001",
      },
    }),
  );
  template.hasResourceProperties("AWS::Lambda::Function", {
    ReservedConcurrentExecutions: 1,
    Timeout: 300,
    Handler: "app.ledger_worker.handler",
    Environment: {
      Variables: Match.objectLike({ DATABASE_SECRET_ARN: readerArn }),
    },
  });
  template.hasResourceProperties("AWS::Events::Rule", {
    ScheduleExpression: "cron(30 0 * * ? *)",
    State: "ENABLED",
    Targets: Match.arrayWith([
      Match.objectLike({
        Input: JSON.stringify({ job: "daily" }),
        RetryPolicy: {
          MaximumEventAgeInSeconds: 7200,
          MaximumRetryAttempts: 2,
        },
        DeadLetterConfig: Match.anyValue(),
      }),
    ]),
  });
  template.hasResourceProperties("AWS::Lambda::EventInvokeConfig", {
    MaximumRetryAttempts: 2,
    MaximumEventAgeInSeconds: 7200,
    DestinationConfig: { OnFailure: Match.anyValue() },
  });
  template.hasResourceProperties("AWS::SQS::Queue", {
    KmsMasterKeyId: Match.anyValue(),
    MessageRetentionPeriod: 1209600,
  });
  template.resourceCountIs("AWS::CloudWatch::Alarm", 3);
  const policies = Object.values(template.findResources("AWS::IAM::Policy"));
  const statements = policies.flatMap(
    (policy) => policy.Properties.PolicyDocument.Statement,
  );
  const secretReads = statements.filter((statement) =>
    [statement.Action].flat().includes("secretsmanager:GetSecretValue"),
  );
  ok(secretReads.length === 1);
  ok(secretReads[0].Resource === readerArn);
  const s3Writes = statements.filter((statement) =>
    [statement.Action].flat().includes("s3:PutObject"),
  );
  ok(s3Writes.length === 1);
  ok(
    JSON.stringify(s3Writes[0].Resource).includes(
      "anchors/00000000-0000-0000-0000-000000000001/",
    ),
  );
});

test("The explicit dev quota fallback does not reserve Lambda concurrency", () => {
  const template = Template.fromStack(
    new CellLedger(new App(), "LowQuotaLedger", {
      stage: "dev",
      tenant: "a",
      worker: {
        bundle: __dirname,
        tenantId: "00000000-0000-0000-0000-000000000001",
        clusterArn: "arn:aws:rds:us-east-1:123456789012:cluster:ci-only",
        readerSecretArn:
          "arn:aws:secretsmanager:us-east-1:123456789012:secret:ci-reader-ABCDEF",
        databaseKeyArn:
          "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000001",
        reserveConcurrency: false,
      },
    }),
  );
  template.hasResourceProperties("AWS::Lambda::Function", {
    Handler: "app.ledger_worker.handler",
    ReservedConcurrentExecutions: Match.absent(),
  });
});

test("CKS ingress is private, IAM-only, role/endpoint-scoped and does not log payloads", () => {
  const app = new App();
  const stack = new Stack(app, "CksBoundary", {
    env: { account: "111111111111", region: "us-east-1" },
  });
  // The ingress references an existing runtime; its packaging/deployment is deliberately separate.
  const handler = LambdaFunction.fromFunctionArn(
    stack,
    "Runtime",
    "arn:aws:lambda:us-east-1:111111111111:function:cks-runtime",
  );
  new CksIngress(stack, "Ingress", {
    handler,
    stage: "v1",
    callers: [
      {
        roleArn: "arn:aws:iam::222222222222:role/reference-client",
        tenantId: "97d7aa7f-d4a0-4af0-ae84-131142081e90",
        endpointIds: ["vpce-0123456789abcdef0"],
        operations: ["normalize", "classes", "labels"],
      },
    ],
  });
  Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
  const template = Template.fromStack(stack);
  template.resourceCountIs("AWS::EC2::NatGateway", 0);
  template.resourceCountIs("AWS::ApiGateway::Method", 3);
  template.resourceCountIs("AWS::Lambda::Permission", 3);
  template.resourceCountIs("AWS::Lambda::Function", 0);
  template.hasResourceProperties("AWS::ApiGateway::RestApi", {
    EndpointConfiguration: { Types: ["PRIVATE"] },
    Policy: {
      Statement: Match.arrayWith([
        Match.objectLike({
          Effect: "Deny",
          Condition: {
            StringNotEquals: { "aws:SourceVpce": ["vpce-0123456789abcdef0"] },
          },
        }),
        Match.objectLike({
          Effect: "Deny",
          Condition: {
            ArnNotEquals: {
              "aws:PrincipalArn": [
                "arn:aws:iam::222222222222:role/reference-client",
              ],
            },
          },
        }),
      ]),
    },
  });
  for (const method of Object.values(
    template.findResources("AWS::ApiGateway::Method"),
  )) {
    ok(method.Properties.AuthorizationType === "AWS_IAM");
    ok(method.Properties.HttpMethod === "POST");
  }
  template.hasResourceProperties("AWS::ApiGateway::Stage", {
    CacheClusterEnabled: false,
    TracingEnabled: true,
    MethodSettings: Match.arrayWith([
      Match.objectLike({ DataTraceEnabled: false }),
    ]),
  });
  template.hasResourceProperties("AWS::Logs::LogGroup", {
    KmsKeyId: Match.anyValue(),
  });
  app.synth();
});

test("CKS ingress rejects empty caller bindings", () => {
  const stack = new Stack(new App(), "InvalidCks");
  const handler = LambdaFunction.fromFunctionArn(
    stack,
    "Runtime",
    "arn:aws:lambda:us-east-1:111111111111:function:cks-runtime",
  );
  let rejected = false;
  try {
    new CksIngress(stack, "Ingress", { handler, stage: "v1", callers: [] });
  } catch {
    rejected = true;
  }
  ok(rejected);
});

test("HubCKS isolates API/cache and permits reference retrieval only through IAM worker", () => {
  const app = new App();
  const stack = new HubCKS(app, "KnowledgeHub", {
    env: { account: "111111111111", region: "us-east-1" },
    bundle: __dirname,
    stage: "dev",
    cacheMajorVersion: "9",
    callers: [
      {
        roleArn: "arn:aws:iam::222222222222:role/reference-client",
        tenantId: "97d7aa7f-d4a0-4af0-ae84-131142081e90",
        endpointIds: ["vpce-0123456789abcdef0"],
        operations: ["normalize", "classes", "labels"],
      },
    ],
  });
  Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
  const template = Template.fromStack(stack);
  template.resourceCountIs("AWS::EC2::NatGateway", 0);
  template.resourceCountIs("AWS::EC2::InternetGateway", 0);
  template.resourceCountIs("AWS::Lambda::Url", 0);
  template.resourceCountIs("AWS::Lambda::Function", 3); // Two app functions plus CDK default-security-group restriction helper.
  template.resourceCountIs("AWS::EC2::VPCEndpoint", 2);
  template.hasResourceProperties("AWS::ElastiCache::ServerlessCache", {
    Engine: "valkey",
    KmsKeyId: Match.anyValue(),
    UserGroupId: Match.anyValue(),
  });
  template.hasResourceProperties("AWS::ElastiCache::User", {
    Engine: "valkey",
    AuthenticationMode: { Type: "password", Passwords: Match.anyValue() },
    AccessString:
      "on ~cks:* -@all +get +set +ping +hello +client|setinfo +client|setname",
  });
  const functions = Object.values(
    template.findResources("AWS::Lambda::Function"),
  );
  const api = functions.find(
    (f) => f.Properties.Handler === "cks.service.handler",
  )!;
  const worker = functions.find(
    (f) => f.Properties.Handler === "cks.bridge.handler",
  )!;
  ok(api.Properties.VpcConfig && !worker.Properties.VpcConfig);
  ok(api.Properties.Environment.Variables.CKS_PRIVATE_MODE === "true");
  ok(!api.Properties.Environment.Variables.VALKEY_URL);
  ok(api.Properties.Environment.Variables.CKS_CACHE_SECRET_ARN);
  const groups = Object.values(
    template.findResources("AWS::EC2::SecurityGroup"),
  );
  for (const group of groups) {
    const ingress = group.Properties.SecurityGroupIngress ?? [];
    ok(
      !ingress.some((rule: { CidrIp?: string }) => rule.CidrIp === "0.0.0.0/0"),
    );
  }
  app.synth();
});

test("FHIR import permissions are scoped to one datastore and encrypted transfer prefixes", () => {
  const app = new App();
  const stack = new CellFhirImport(app, "Import", {
    stage: "dev",
    tenant: "a",
    env: { account: "111111111111", region: "us-east-1" },
    datastoreArn:
      "arn:aws:healthlake:us-east-1:111111111111:datastore/fhir/0123456789abcdef0123456789abcdef",
  });
  Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
  const template = Template.fromStack(stack);
  template.resourceCountIs("AWS::HealthLake::FHIRDatastore", 0);
  template.hasResourceProperties("AWS::S3::Bucket", {
    VersioningConfiguration: { Status: "Enabled" },
    BucketEncryption: {
      ServerSideEncryptionConfiguration: Match.arrayWith([
        Match.objectLike({
          ServerSideEncryptionByDefault: {
            SSEAlgorithm: "aws:kms",
            KMSMasterKeyID: Match.anyValue(),
          },
        }),
      ]),
    },
  });
  template.hasResourceProperties("AWS::IAM::Role", {
    AssumeRolePolicyDocument: {
      Statement: Match.arrayWith([
        Match.objectLike({
          Principal: { Service: "healthlake.amazonaws.com" },
          Condition: {
            StringEquals: { "aws:SourceAccount": "111111111111" },
            ArnEquals: {
              "aws:SourceArn":
                "arn:aws:healthlake:us-east-1:111111111111:datastore/fhir/0123456789abcdef0123456789abcdef",
            },
          },
        }),
      ]),
    },
  });
  app.synth();
});
