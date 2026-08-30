export const APP_THEME_STORAGE_KEY = 'smartcomp-theme';

export function isAppTheme(value) {
  return value === 'light' || value === 'dark';
}

export function getAppThemeStorage(browser) {
  try {
    return browser?.localStorage ?? null;
  } catch {
    return null;
  }
}

export function resolveAppTheme(storedTheme, systemPrefersDark = false) {
  if (isAppTheme(storedTheme)) return storedTheme;
  return systemPrefersDark ? 'dark' : 'light';
}

export function readStoredAppTheme(storage) {
  if (!storage) return null;
  try {
    const value = storage.getItem(APP_THEME_STORAGE_KEY);
    return isAppTheme(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeStoredAppTheme(storage, value) {
  if (!storage || !isAppTheme(value)) return false;
  try {
    storage.setItem(APP_THEME_STORAGE_KEY, value);
    return true;
  } catch {
    return false;
  }
}

export function getNextAppTheme(current) {
  return current === 'dark' ? 'light' : 'dark';
}

export function applyAppTheme(root, value) {
  const resolved = isAppTheme(value) ? value : 'light';
  if (root?.dataset) root.dataset.theme = resolved;
  if (root?.style) root.style.colorScheme = resolved;
  return resolved;
}
