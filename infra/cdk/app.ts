import { App, Validations } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
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
