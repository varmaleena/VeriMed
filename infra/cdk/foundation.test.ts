import { test } from "node:test";
import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { CellFoundation, HubFoundation } from "./foundation";
import { CellIdentity } from "./cell-identity";
import { CellWorklist } from "./cell-worklist";
import { CellFhirDemo } from "./cell-fhir-demo";

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
