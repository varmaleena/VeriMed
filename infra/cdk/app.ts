import { App, Validations } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
import { CellIdentity } from "./cell-identity";
import { AgentCoreSpike } from "./agentcore-spike";
import { FhirSpike } from "./fhir-spike";
import { HealthScribeSpike } from "./healthscribe-spike";
import { LiteLlmSpike } from "./litellm-spike";
import { CellFoundation, HubFoundation } from "./foundation";

const app = new App();
const stage: string = app.node.tryGetContext("env") ?? "dev";
const tenant: string = app.node.tryGetContext("cell") ?? "a";
const region = process.env.AWS_REGION ?? "us-east-1";
new HubFoundation(app, "HubFoundation", {
  stage,
  tenant: "hub",
  env: { region, account: process.env.VERIMED_HUB_ACCOUNT },
});
new CellFoundation(app, "CellFoundation", {
  stage,
  tenant,
  env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
});
Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
if (app.node.tryGetContext("cellIdentity") === "true") {
  new CellIdentity(app, "CellIdentity", {
    demoWithoutMfa: app.node.tryGetContext("demoWithoutMfa") === "true",
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("agentCoreSpike") === "true") {
  const bundle = process.env.VERIMED_AGENTCORE_BUNDLE;
  const profileId = process.env.MODEL_CHALLENGER_ID;
  const modelArns = process.env.VERIMED_SPIKE_MODEL_ARNS?.split(",");
  if (!bundle || !profileId || !modelArns?.length) {
    throw new Error(
      "Provide the temporary Runtime bundle and Bedrock inference profile configuration",
    );
  }
  new AgentCoreSpike(app, "AgentCoreSpike", {
    bundle,
    profileId,
    modelArns,
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("fhirSpike") === "true") {
  new FhirSpike(app, "FhirSpike", {
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("healthscribeSpike") === "true") {
  new HealthScribeSpike(app, "HealthScribeSpike", {
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("liteLlmSpike") === "true") {
  new LiteLlmSpike(app, "LiteLlmSpike", {
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
