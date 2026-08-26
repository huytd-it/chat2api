import { get, writable } from "svelte/store";
import { apiKey, showToast } from "./stores";
import {
  fetchAccounts,
  fetchDomains,
  fetchModels,
  fetchOverview,
  fetchProfiles,
  fetchRecipes,
  type DomainAccounts,
  type DomainInfo,
  type ModelInfo,
  type Overview,
  type ProfileInfo,
  type ProfileList,
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

// Profile Chromium: hàng DB, nên danh sách rỗng cũng có thể chỉ là "kho chưa
// mở" — `profilesMeta.persisted` phân biệt hai trường hợp đó cho UI.
export const profiles = writable<ProfileInfo[]>([]);
export const profilesMeta = writable<Omit<ProfileList, "profiles"> | null>(null);
export const profilesLoading = writable(false);

export async function refreshProfiles() {
  profilesLoading.set(true);
  try {
    const { profiles: list, ...meta } = await fetchProfiles(get(apiKey));
    profiles.set(list);
    profilesMeta.set(meta);
  } catch {
    profiles.set([]);
    profilesMeta.set(null);
  } finally {
    profilesLoading.set(false);
  }
}

/** Domain đã biết — chỉ dùng để gợi ý trong ô Domain, hỏng thì im lặng bỏ qua. */
export const domains = writable<DomainInfo[]>([]);

export async function refreshDomains() {
  try {
    domains.set(await fetchDomains(get(apiKey)));
  } catch {
    domains.set([]);
  }
}

/** Mọi thứ trang Integrations hiển thị, nạp trong một lượt — chỉ dùng cho lần
 * tải đầu tiên; các thao tác đơn lẻ nên gọi refreshX() đúng phần bị ảnh hưởng
 * để tránh giật hình toàn trang (xem refreshAfterRecipeChange/Delete bên dưới). */
export async function refreshIntegrations() {
  await Promise.all([refreshRecipes(), refreshAccounts(), refreshProfiles(), refreshDomains()]);
}

/** Sau reload/tạo mới một recipe: health và model có thể đổi. */
export async function refreshAfterRecipeChange() {
  await Promise.all([refreshRecipes(), refreshModels()]);
}

/** Sau khi xóa một recipe: domain của nó có thể thành orphan, model mất theo. */
export async function refreshAfterRecipeDelete() {
  await Promise.all([refreshRecipes(), refreshAccounts(), refreshDomains(), refreshModels()]);
}
