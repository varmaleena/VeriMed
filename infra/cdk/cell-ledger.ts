import {
  CfnOutput,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
  Validations,
} from "aws-cdk-lib";
import { Key, KeySpec, KeyUsage } from "aws-cdk-lib/aws-kms";
import { Construct } from "constructs";

interface LedgerProps extends StackProps {
  stage: string;
  tenant: string;
}

export class CellLedger extends Stack {
  constructor(scope: Construct, id: string, props: LedgerProps) {
    super(scope, id, props);
    Tags.of(this).add("Project", "verimed");
    Tags.of(this).add("Tenant", props.tenant);
    Tags.of(this).add("Env", props.stage);
    const signingKey = new Key(this, "SigningKey", {
      description: "ChartVigil tenant audit ledger signatures",
      keySpec: KeySpec.ECC_NIST_P256,
      keyUsage: KeyUsage.SIGN_VERIFY,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    // AWS KMS automatic rotation supports symmetric encryption keys only.
    // Rotate by provisioning a new key, retaining old ARNs for historical verification.
    Validations.of(signingKey).acknowledge({
      id: "AwsSolutions::AwsSolutions-KMS4",
      reason:
        "Asymmetric signing keys do not support automatic rotation; retain historical keys and rotate through new versioned keys.",
    });
    new CfnOutput(this, "SigningKeyArn", { value: signingKey.keyArn });
  }
}
