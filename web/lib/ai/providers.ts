import { createGateway } from "@ai-sdk/gateway";
import {
  customProvider,
  extractReasoningMiddleware,
  wrapLanguageModel,
} from "ai";
import { isTestEnvironment } from "../constants";
import { getAiGatewayApiKey } from "../server-config";
import { generatedAux, generatedModels } from "./catalog.generated";

const AUX_GATEWAY_FALLBACK = "anthropic/claude-haiku-4.5";

export function resolveAuxGatewayId(
  slot: "fast" | "title" | "artifact",
  aux: Record<string, string> = generatedAux,
  models: ReadonlyArray<{ id: string; catalog_id: string }> = generatedModels
): string {
  const pin = aux[slot];
  if (!pin) {
    return AUX_GATEWAY_FALLBACK;
  }
  const row = models.find((model) => model.catalog_id === pin);
  return row?.id ?? AUX_GATEWAY_FALLBACK;
}

const THINKING_SUFFIX_REGEX = /-thinking$/;

const gateway = createGateway({
  apiKey: getAiGatewayApiKey(),
});

export const myProvider = isTestEnvironment
  ? (() => {
      const {
        artifactModel,
        chatModel,
        reasoningModel,
        titleModel,
      } = require("./models.mock");
      return customProvider({
        languageModels: {
          "chat-model": chatModel,
          "chat-model-reasoning": reasoningModel,
          "title-model": titleModel,
          "artifact-model": artifactModel,
        },
      });
    })()
  : null;

export function getLanguageModel(modelId: string) {
  if (isTestEnvironment && myProvider) {
    return myProvider.languageModel(modelId);
  }

  const isReasoningModel =
    modelId.includes("reasoning") || modelId.endsWith("-thinking");

  if (isReasoningModel) {
    const gatewayModelId = modelId.replace(THINKING_SUFFIX_REGEX, "");

    return wrapLanguageModel({
      model: gateway.languageModel(gatewayModelId),
      middleware: extractReasoningMiddleware({ tagName: "thinking" }),
    });
  }

  return gateway.languageModel(modelId);
}

export function getTitleModel() {
  if (isTestEnvironment && myProvider) {
    return myProvider.languageModel("title-model");
  }
  return gateway.languageModel(resolveAuxGatewayId("title"));
}

export function getArtifactModel() {
  if (isTestEnvironment && myProvider) {
    return myProvider.languageModel("artifact-model");
  }
  return gateway.languageModel(resolveAuxGatewayId("artifact"));
}
