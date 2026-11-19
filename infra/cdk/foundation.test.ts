import { test } from "node:test";
import { ok } from "node:assert/strict";
import { App, Stack, Validations } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
import { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { CksIngress } from "./cks-ingress";
import { Match, Template } from "aws-cdk-lib/assertions";
import { CellFoundation, HubFoundation } from "./foundation";
import { CellIdentity } from "./cell-identity";
import { CellWorklist } from "./cell-worklist";
import { CellFhirDemo } from "./cell-fhir-demo";
import { CellLedger } from "./cell-ledger";

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
    }),
  );
  template.resourceCountIs("AWS::EC2::NatGateway", 0);
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
