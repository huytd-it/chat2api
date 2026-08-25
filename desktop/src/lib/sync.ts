import { get, writable } from "svelte/store";
import { apiKey, showToast } from "./stores";
import {
  fetchAccounts,
  fetchModels,
  fetchOverview,
  fetchRecipes,
  type DomainAccounts,
  type ModelInfo,
  type Overview,
  type RecipeInfo,
} from "./api";

export const models = writable<ModelInfo[]>([]);
export const modelsLoading = writable(false);
export const modelsError = writable(false);
export const selectedModel = writable<string>("");

export const recipes = writable<RecipeInfo[]>([]);
export const recipesLoading = writable(false);
export const recipesError = writable(false);

export async function refreshModels() {
  modelsLoading.set(true);
  try {
    const list = await fetchModels(get(apiKey));
    models.set(list);
    modelsError.set(false);
    if (!list.some((m) => m.id === get(selectedModel))) {
      selectedModel.set(list[0]?.id ?? "");
    }
  } catch (e) {
    models.set([]);
    modelsError.set(true);
    showToast("Không nạp được models: " + (e as Error).message);
  } finally {
    modelsLoading.set(false);
  }
}

export const accounts = writable<DomainAccounts[]>([]);
export const accountsLoading = writable(false);
export const accountsError = writable(false);

export const overview = writable<Overview | null>(null);

export async function refreshRecipes() {
  recipesLoading.set(true);
  try {
    const list = await fetchRecipes(get(apiKey));
    recipes.set(list);
    recipesError.set(false);
  } catch {
    recipes.set([]);
    recipesError.set(true);
  } finally {
    recipesLoading.set(false);
  }
}

export async function refreshAccounts() {
  accountsLoading.set(true);
  try {
    accounts.set(await fetchAccounts(get(apiKey)));
    accountsError.set(false);
  } catch (e) {
    accounts.set([]);
    accountsError.set(true);
    showToast("Không nạp được accounts: " + (e as Error).message);
  } finally {
    accountsLoading.set(false);
  }
}

export async function refreshOverview() {
  try {
    overview.set(await fetchOverview(get(apiKey)));
  } catch {
    overview.set(null);
  }
}
