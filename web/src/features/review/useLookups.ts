import { useEffect, useMemo, useState } from "react";
import { reviewApi, type AccountInfo, type AppInfo, type FormatInfo } from "./api";

export type Lookups = {
  appName: (id: string) => string;
  appCount: number;
  account: (id: string) => AccountInfo | undefined;
  formatTitle: (id: string) => string;
};

/** Noms des apps, pseudos des comptes, titres des formats : chargés une fois, la page s'en passe s'ils manquent. */
export function useLookups(): Lookups {
  const [apps, setApps] = useState<AppInfo[]>([]);
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [formats, setFormats] = useState<FormatInfo[]>([]);

  useEffect(() => {
    reviewApi.apps().then(setApps, () => {});
    reviewApi.accounts().then(setAccounts, () => {});
    reviewApi.formats().then(setFormats, () => {});
  }, []);

  return useMemo(() => {
    const appById = new Map(apps.map((a) => [a.id, a]));
    const accountById = new Map(accounts.map((a) => [a.id, a]));
    const formatById = new Map(formats.map((f) => [f.id, f]));
    return {
      appName: (id) => appById.get(id)?.name ?? id,
      appCount: apps.length,
      account: (id) => accountById.get(id),
      formatTitle: (id) => formatById.get(id)?.title ?? id,
    };
  }, [apps, accounts, formats]);
}
