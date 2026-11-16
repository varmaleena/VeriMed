import { CfnOutput, Stack, StackProps } from "aws-cdk-lib";
import { CfnGuardrail, CfnGuardrailVersion } from "aws-cdk-lib/aws-bedrock";
import { Construct } from "constructs";

export class LiteLlmSpike extends Stack {
  constructor(scope: Construct, id: string, props: StackProps) {
    super(scope, id, props);
    const guardrail = new CfnGuardrail(this, "Guardrail", {
      name: "verimed-phase-zero-spike",
      blockedInputMessaging: "verimed-spike-input-blocked",
      blockedOutputsMessaging: "verimed-spike-output-blocked",
      wordPolicyConfig: { wordsConfig: [{ text: "verimedspikeblocktoken" }] },
    });
    const version = new CfnGuardrailVersion(this, "GuardrailVersion", {
      guardrailIdentifier: guardrail.attrGuardrailId,
    });
    new CfnOutput(this, "GuardrailId", { value: guardrail.attrGuardrailId });
    new CfnOutput(this, "GuardrailVersionNumber", {
      value: version.attrVersion,
    });
  }
}
