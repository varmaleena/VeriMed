import { test } from "node:test";
import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { CellFoundation, HubFoundation } from "./foundation";
import { CellIdentity } from "./cell-identity";

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
