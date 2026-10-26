import { frenchNote, healthDetail } from "../lib/adminText";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, hasAdminAccess, hasScope, SERVICE_SCOPES } from "../lib/api";
import type {
  ApplicationItem,
  AuditQuery,
  BucketListedItem,
  IdentityItem,
  PartnerSite,
  SpaceItem,
  SpaceQuota,
} from "../lib/api";
import { useAuth, useSession } from "../lib/auth";
import { ConfirmAction, Dialog } from "../components/Dialog";
import { OneTimeToken } from "../components/OneTimeToken";
import { Loading, LoadError } from "../components/Loading";
import { describeError } from "../lib/errors";

const DATE_FMT = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatTs(ts: number | null | undefined): string {
  if (!ts) {
    return "—";
  }
  return DATE_FMT.format(new Date(ts * 1000));
}

/** Lifecycle label for a machine identity, derived from the API fields. */
function identityState(item: IdentityItem): { label: string; className: string } {
  if (item.revoked_at) {
    return { label: "Révoquée", className: "chip chip-muted" };
  }
  if (item.expires_at && item.expires_at * 1000 < Date.now()) {
    return { label: "Expirée", className: "chip chip-warn" };
  }
  return { label: "Active", className: "chip chip-ok" };
}

/**
 * State of a partner integration, derived from its identity: the site itself
 * has no lifecycle, the key does.
 */
function partnerState(site: PartnerSite): { label: string; className: string } {
  if (site.identity.revoked_at) {
    return { label: "Clé révoquée", className: "chip chip-muted" };
  }
  if (site.identity.expires_at && site.identity.expires_at * 1000 < Date.now()) {
    return { label: "Clé expirée", className: "chip chip-warn" };
  }
  return { label: "Clé active", className: "chip chip-ok" };
}

const GIB = 1024 ** 3;

/** Percentage of a quota used, or null when no quota is configured. */
function quotaPct(used: number, limit: number | null): number | null {
  if (limit === null || limit <= 0) return null;
  return Math.min(999, Math.round((used / limit) * 100));
}

/** Chip class for a quota: warn at 80 %, danger at 100 %. */
function quotaChip(pct: number | null): { label: string; className: string } | null {
  if (pct === null) return null;
  if (pct >= 100) return { label: `${pct} % · dépassé`, className: "chip chip-warn" };
  if (pct >= 80) return { label: `${pct} % · proche`, className: "chip chip-warn" };
  return { label: `${pct} %`, className: "chip chip-muted" };
}

function gibToBytes(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n <= 0) return null;
  return Math.round(n * GIB);
}

function bytesToGib(value: number | null): string {
  if (value === null || value <= 0) return "";
  const n = value / GIB;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

/** Seconds -> a short human duration for the media-TTL recommendation. */
function formatTtl(seconds: number | null): string {
  if (!seconds) return "—";
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

/** Active/disabled chip shared by applications and spaces. */
function lifecycleState(status: string): { label: string; className: string } {
  return status === "active"
    ? { label: "Actif", className: "chip chip-ok" }
    : { label: "Désactivé", className: "chip chip-muted" };
}

/** French labels for object lifecycle states (same words as the files screen). */
const OBJECT_STATUS_LABELS: Record<string, string> = {
  available: "Disponible",
  pending: "En cours",
  verifying: "Vérification",
  deleted: "Supprimé",
  purging: "Purge en cours",
  expired: "Expiré",
  failed: "Échec",
};

/** Human byte counts for the consumption section (measured values only). */
function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) {
    return "—";
  }
  if (size === 0) {
    return "0 o";
  }
  const units = ["o", "Ko", "Mo", "Go", "To"];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

const AUDIT_PAGE_SIZE = 50;

/** Sections of the console, one tab each (labels are what the user reads). */
const ADMIN_TABS = [
  { id: "overview", label: "Vue d'ensemble" },
  { id: "audit", label: "Journal d'audit" },
  { id: "apps", label: "Applications et espaces" },
  { id: "buckets", label: "Buckets" },
  { id: "identities", label: "Identités de service" },
  { id: "partners", label: "Intégrations" },
] as const;

type AdminTab = (typeof ADMIN_TABS)[number]["id"];

function tabFromHash(): AdminTab {
  const wanted = window.location.hash.replace(/^#/, "");
  return ADMIN_TABS.find((tab) => tab.id === wanted)?.id ?? "overview";
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Human label for an audit result (the stored value stays machine-readable). */
function resultLabel(result: string): string {
  if (result === "success") return "Réussi";
  if (result === "failure") return "Refusé";
  return result;
}

/** Rename an application. The stable id is never editable. */
function EditApplicationDialog({
  application,
  pending,
  onClose,
  onSubmit,
}: {
  application: ApplicationItem;
  pending: boolean;
  onClose: () => void;
  onSubmit: (name: string) => void;
}) {
  const [name, setName] = useState(application.name);
  const trimmed = name.trim();
  const invalid = trimmed.length === 0 || trimmed.length > 63;
  return (
    <Dialog open title="Modifier l'application" onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!invalid) onSubmit(trimmed);
        }}
      >
        <label className="field">
          <span>Nom</span>
          <input
            type="text"
            value={name}
            maxLength={63}
            required
            autoFocus
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <p className="muted">
          Identifiant stable : <code>{application.id}</code>
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Annuler
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={invalid || pending}
          >
            {pending ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** Rename / re-environment a space. The owning application is read-only. */
function EditSpaceDialog({
  space,
  applicationName,
  pending,
  onClose,
  onSubmit,
}: {
  space: SpaceItem;
  applicationName: string;
  pending: boolean;
  onClose: () => void;
  onSubmit: (patch: { name: string; environment: string }) => void;
}) {
  const [name, setName] = useState(space.name);
  const [environment, setEnvironment] = useState(space.environment);
  const trimmedName = name.trim();
  const trimmedEnv = environment.trim();
  const invalid =
    trimmedName.length === 0 ||
    trimmedName.length > 63 ||
    trimmedEnv.length === 0 ||
    trimmedEnv.length > 32;
  return (
    <Dialog open title="Modifier l'espace" onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!invalid) onSubmit({ name: trimmedName, environment: trimmedEnv });
        }}
      >
        <label className="field">
          <span>Nom</span>
          <input
            type="text"
            value={name}
            maxLength={63}
            required
            autoFocus
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Environnement</span>
          <input
            type="text"
            value={environment}
            maxLength={32}
            required
            onChange={(e) => setEnvironment(e.target.value)}
          />
        </label>
        <p className="muted">
          Application : <strong>{applicationName}</strong> — l'association à une
          application n'est pas modifiable. Identifiant stable :{" "}
          <code>{space.id}</code>
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Annuler
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={invalid || pending}
          >
            {pending ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** Edit the trust metadata of a partner site. The key and the space are fixed. */
function EditPartnerDialog({
  site,
  pending,
  onClose,
  onSubmit,
}: {
  site: PartnerSite;
  pending: boolean;
  onClose: () => void;
  onSubmit: (patch: {
    name: string;
    site_url: string;
    default_ttl_seconds: number | null;
    notes: string;
  }) => void;
}) {
  const [name, setName] = useState(site.name);
  const [siteUrl, setSiteUrl] = useState(site.site_url);
  const [ttl, setTtl] = useState(
    site.default_ttl_seconds === null ? "" : String(site.default_ttl_seconds),
  );
  const [notes, setNotes] = useState(site.notes);
  const trimmedName = name.trim();
  const trimmedUrl = siteUrl.trim();
  const parsedTtl = Number.parseInt(ttl, 10);
  const ttlInvalid = ttl.trim() !== "" && (!Number.isFinite(parsedTtl) || parsedTtl < 60);
  const invalid =
    trimmedName.length === 0 || trimmedName.length > 63 || trimmedUrl.length < 8;
  return (
    <Dialog open title={`Modifier ${site.name}`} onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (invalid || ttlInvalid) return;
          onSubmit({
            name: trimmedName,
            site_url: trimmedUrl,
            default_ttl_seconds: ttl.trim() === "" ? null : parsedTtl,
            notes: notes.trim(),
          });
        }}
      >
        <label className="field">
          <span>Nom du site</span>
          <input
            type="text"
            value={name}
            maxLength={63}
            required
            autoFocus
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Origine (https)</span>
          <input
            type="url"
            value={siteUrl}
            required
            onChange={(e) => setSiteUrl(e.target.value)}
          />
        </label>
        <label className="field">
          <span>TTL média conseillé (secondes, vide = aucun)</span>
          <input
            type="number"
            min="60"
            max="604800"
            value={ttl}
            onChange={(e) => setTtl(e.target.value)}
            aria-invalid={ttlInvalid ? "true" : undefined}
          />
        </label>
        <label className="field">
          <span>Notes</span>
          <textarea
            rows={3}
            value={notes}
            maxLength={2000}
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>
        <p className="muted">
          Espace et clé non modifiables : pour changer d'espace, créez une
          nouvelle intégration et révoquez l'ancienne.
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Annuler
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={invalid || ttlInvalid || pending}
          >
            {pending ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** Monthly storage/egress ceilings for one space. Empty means "no quota". */
function SpaceQuotasDialog({
  space,
  quota,
  storedBytes,
  egressBytes,
  pending,
  onClose,
  onSubmit,
}: {
  space: SpaceItem;
  quota: SpaceQuota;
  storedBytes: number;
  egressBytes: number;
  pending: boolean;
  onClose: () => void;
  onSubmit: (input: {
    storage_bytes: number | null;
    egress_bytes_monthly: number | null;
  }) => void;
}) {
  const [storage, setStorage] = useState(bytesToGib(quota.storage_bytes));
  const [egress, setEgress] = useState(bytesToGib(quota.egress_bytes_monthly));
  const invalid =
    (storage.trim() !== "" && gibToBytes(storage) === null) ||
    (egress.trim() !== "" && gibToBytes(egress) === null);
  return (
    <Dialog open title={`Quotas — ${space.name}`} onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (invalid) return;
          onSubmit({
            storage_bytes: gibToBytes(storage),
            egress_bytes_monthly: gibToBytes(egress),
          });
        }}
      >
        <p className="muted">
          Usage actuel : {formatBytes(storedBytes)} stockés et{" "}
          {formatBytes(egressBytes)} de trafic estimé ce mois. Le stockage est
          refusé au-delà de son quota ; le trafic est estimé à partir des
          intentions émises.
        </p>
        <label className="field">
          <span>Quota de stockage (Go, vide = aucun)</span>
          <input
            type="number"
            min="0"
            step="1"
            value={storage}
            onChange={(e) => setStorage(e.target.value)}
            aria-invalid={storage.trim() !== "" && gibToBytes(storage) === null}
          />
        </label>
        <label className="field">
          <span>Quota de trafic mensuel (Go, vide = aucun)</span>
          <input
            type="number"
            min="0"
            step="1"
            value={egress}
            onChange={(e) => setEgress(e.target.value)}
            aria-invalid={egress.trim() !== "" && gibToBytes(egress) === null}
          />
        </label>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn btn-primary" disabled={invalid || pending}>
            {pending ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** Administration console: registries plus `admin:write` mutations. */
export function AdminPage() {
  const { csrf } = useAuth();
  const session = useSession();
  const queryClient = useQueryClient();
  const canAdmin = hasAdminAccess(session.data?.role);
  const canWrite = hasScope(session.data?.scopes, "admin:write");

  const [tab, setTab] = useState<AdminTab>(tabFromHash);
  // A link such as /admin#audit must work while the page is already open.
  useEffect(() => {
    const onHashChange = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  const [error, setError] = useState<string | null>(null);
  const [oneTimeToken, setOneTimeToken] = useState<string | null>(null);
  const [editingApp, setEditingApp] = useState<ApplicationItem | null>(null);
  const [editingSpace, setEditingSpace] = useState<SpaceItem | null>(null);
  const [editingQuotas, setEditingQuotas] = useState<SpaceItem | null>(null);

  // Create-application form
  const [appName, setAppName] = useState("");
  // Create-space form
  const [spaceApp, setSpaceApp] = useState("");
  const [spaceName, setSpaceName] = useState("");
  const [spaceEnv, setSpaceEnv] = useState("prod");
  const [spaceBucket, setSpaceBucket] = useState("");
  // Create-identity form
  const [idName, setIdName] = useState("");
  const [idSpace, setIdSpace] = useState("");
  const [idScopes, setIdScopes] = useState<string[]>(["objects:read"]);
  const [idTtlDays, setIdTtlDays] = useState("");
  // Create-partner form (site metadata + its dedicated identity)
  const [partnerName, setPartnerName] = useState("");
  const [partnerUrl, setPartnerUrl] = useState("");
  const [partnerSpace, setPartnerSpace] = useState("");
  const [partnerScopes, setPartnerScopes] = useState<string[]>(["objects:read"]);
  const [partnerTtlDays, setPartnerTtlDays] = useState("");
  const [partnerMediaTtl, setPartnerMediaTtl] = useState("900");
  const [partnerNotes, setPartnerNotes] = useState("");
  const [editingPartner, setEditingPartner] = useState<PartnerSite | null>(null);
  const [copiedPartnerId, setCopiedPartnerId] = useState<string | null>(null);
  // Register-bucket form
  const [bucketSpace, setBucketSpace] = useState("");
  const [bucketName, setBucketName] = useState("");
  // Audit search form (M07): draft fields, applied query, paging offset.
  const [auditActor, setAuditActor] = useState("");
  const [auditAction, setAuditAction] = useState("");
  const [auditResult, setAuditResult] = useState("");
  const [auditSpace, setAuditSpace] = useState("");
  const [auditRequest, setAuditRequest] = useState("");
  const [auditApplied, setAuditApplied] = useState<AuditQuery>({});
  const [auditOffset, setAuditOffset] = useState(0);

  const stats = useQuery({
    queryKey: ["admin", "stats"],
    queryFn: () => api.adminStats(),
    enabled: canAdmin,
    retry: false,
  });
  const applications = useQuery({
    queryKey: ["admin", "applications"],
    queryFn: () => api.listApplications(),
    enabled: canAdmin,
    retry: false,
  });
  const spaces = useQuery({
    queryKey: ["admin", "spaces"],
    queryFn: () => api.listSpaces(),
    enabled: canAdmin,
    retry: false,
  });
  const identities = useQuery({
    queryKey: ["admin", "identities"],
    queryFn: () => api.listIdentities(),
    enabled: canAdmin,
    retry: false,
  });
  const partnerSites = useQuery({
    queryKey: ["admin", "partner-sites"],
    queryFn: () => api.listPartnerSites(),
    enabled: canAdmin,
    retry: false,
  });
  const buckets = useQuery({
    queryKey: ["admin", "buckets"],
    queryFn: () => api.listBuckets(),
    enabled: canAdmin,
    retry: false,
  });
  const usage = useQuery({
    queryKey: ["admin", "usage"],
    queryFn: () => api.adminUsage(),
    enabled: canAdmin,
    retry: false,
  });
  const health = useQuery({
    queryKey: ["admin", "health"],
    queryFn: () => api.adminHealth(),
    enabled: canAdmin,
    retry: false,
  });
  const orphans = useQuery({
    queryKey: ["admin", "orphans"],
    queryFn: () => api.adminOrphans(),
    enabled: canAdmin,
    retry: false,
  });
  // Lists whole buckets: only on demand, never on page load.
  const storageOrphans = useQuery({
    queryKey: ["admin", "storage-orphans"],
    queryFn: () => api.adminStorageOrphans(),
    enabled: false,
    retry: false,
  });
  const integrity = useQuery({
    queryKey: ["admin", "integrity"],
    queryFn: () => api.adminIntegrity(),
    enabled: canAdmin,
    retry: false,
  });
  const auditSearch = useQuery({
    queryKey: ["admin", "audit", auditApplied, auditOffset],
    queryFn: () =>
      api.searchAudit({ ...auditApplied, limit: AUDIT_PAGE_SIZE, offset: auditOffset }),
    enabled: canAdmin,
    retry: false,
  });

  /** Name a known actor: the signed-in account and service identities are
   * resolved from data already loaded; any other id stays shortened (the API
   * has no user directory), with the full value kept in the tooltip. */
  function actorLabel(actor: string | null | undefined): { text: string; title?: string } {
    if (!actor) return { text: "—" };
    if (session.data?.id === actor && session.data.name) {
      return { text: `${session.data.name} (vous)`, title: actor };
    }
    const identity = identities.data?.items.find((item) => item.id === actor);
    if (identity) return { text: identity.name, title: actor };
    if (UUID_PATTERN.test(actor)) return { text: `${actor.slice(0, 8)}…`, title: actor };
    return { text: actor };
  }

  function selectTab(next: AdminTab) {
    setTab(next);
    window.history.replaceState(null, "", `#${next}`);
  }

  function refreshAdmin() {
    void queryClient.invalidateQueries({ queryKey: ["admin"] });
  }

  /** What failed, then why in plain words (never a raw "API 409: …"). */
  function fail(err: unknown, fallback: string) {
    setError(`${fallback} ${describeError(err, "")}`.trim());
  }

  const reconcile = useMutation({
    mutationFn: () => {
      if (!csrf) throw new Error("Session expirée.");
      return api.reconcile(csrf);
    },
    onSuccess: () => {
      setError(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Réconciliation impossible."),
  });

  const pruneAudit = useMutation({
    mutationFn: () => {
      if (!csrf) throw new Error("Session expirée.");
      return api.pruneAudit(csrf);
    },
    onSuccess: () => {
      setError(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Purge du journal impossible."),
  });

  const createApp = useMutation({
    mutationFn: (name: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.createApplication(name, csrf);
    },
    onSuccess: () => {
      setError(null);
      setAppName("");
      refreshAdmin();
    },
    onError: (err) => fail(err, "Création d'application impossible."),
  });

  const updateApp = useMutation({
    mutationFn: (input: { id: string; name: string }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.updateApplication(input.id, { name: input.name }, csrf);
    },
    onSuccess: () => {
      setError(null);
      setEditingApp(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Modification de l'application impossible."),
  });

  const setAppStatus = useMutation({
    mutationFn: (input: { id: string; status: string }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.updateApplication(input.id, { status: input.status }, csrf);
    },
    onSuccess: () => {
      setError(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Changement d'état impossible."),
  });

  const createSpace = useMutation({
    mutationFn: () => {
      if (!csrf) throw new Error("Session expirée.");
      const body: {
        application_id: string;
        name: string;
        environment: string;
        default_bucket?: string;
      } = { application_id: spaceApp, name: spaceName, environment: spaceEnv };
      if (spaceBucket.trim()) body.default_bucket = spaceBucket.trim();
      return api.createSpace(body, csrf);
    },
    onSuccess: () => {
      setError(null);
      setSpaceName("");
      setSpaceBucket("");
      refreshAdmin();
    },
    onError: (err) => fail(err, "Création d'espace impossible."),
  });

  const updateSpace = useMutation({
    mutationFn: (input: { id: string; name: string; environment: string }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.updateSpace(
        input.id,
        { name: input.name, environment: input.environment },
        csrf,
      );
    },
    onSuccess: () => {
      setError(null);
      setEditingSpace(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Modification de l'espace impossible."),
  });

  const setSpaceQuotas = useMutation({
    mutationFn: (input: {
      id: string;
      storage_bytes: number | null;
      egress_bytes_monthly: number | null;
    }) => {
      if (!csrf) throw new Error("Session expirée.");
      const { id, ...quotas } = input;
      return api.setSpaceQuotas(id, quotas, csrf);
    },
    onSuccess: () => {
      setError(null);
      setEditingQuotas(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Enregistrement des quotas impossible."),
  });

  const setSpaceStatus = useMutation({
    mutationFn: (input: { id: string; status: string }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.updateSpace(input.id, { status: input.status }, csrf);
    },
    onSuccess: () => {
      setError(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Changement d'état impossible."),
  });

  const createBucket = useMutation({
    mutationFn: () => {
      if (!csrf) throw new Error("Session expirée.");
      return api.createSpaceBucket(bucketSpace, bucketName.trim(), csrf);
    },
    onSuccess: () => {
      setError(null);
      setBucketName("");
      refreshAdmin();
    },
    onError: (err) => fail(err, "Enregistrement du bucket impossible."),
  });

  const setBucketDefault = useMutation({
    mutationFn: (input: { id: string; isDefault: boolean }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.updateBucket(input.id, input.isDefault, csrf);
    },
    onSuccess: () => {
      setError(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Mise à jour du bucket impossible."),
  });

  const createIdentity = useMutation({
    mutationFn: () => {
      if (!csrf) throw new Error("Session expirée.");
      const body: {
        space_id: string;
        name: string;
        scopes: string[];
        ttl_seconds?: number;
      } = { space_id: idSpace, name: idName, scopes: idScopes };
      const days = Number.parseInt(idTtlDays, 10);
      if (Number.isFinite(days) && days > 0) body.ttl_seconds = days * 86400;
      return api.createIdentity(body, csrf);
    },
    onSuccess: (data) => {
      setError(null);
      setIdName("");
      setOneTimeToken(data.token);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Création d'identité impossible."),
  });

  const createPartner = useMutation({
    mutationFn: () => {
      if (!csrf) throw new Error("Session expirée.");
      const body = {
        name: partnerName.trim(),
        site_url: partnerUrl.trim(),
        space_id: partnerSpace,
        scopes: partnerScopes,
        notes: partnerNotes.trim(),
      } as {
        name: string;
        site_url: string;
        space_id: string;
        scopes: string[];
        notes: string;
        ttl_seconds?: number;
        default_ttl_seconds?: number;
      };
      const days = Number.parseInt(partnerTtlDays, 10);
      if (Number.isFinite(days) && days > 0) body.ttl_seconds = days * 86400;
      const media = Number.parseInt(partnerMediaTtl, 10);
      if (Number.isFinite(media) && media >= 60) body.default_ttl_seconds = media;
      return api.createPartnerSite(body, csrf);
    },
    onSuccess: (data) => {
      setError(null);
      setPartnerName("");
      setPartnerUrl("");
      setPartnerNotes("");
      setPartnerTtlDays("");
      setPartnerMediaTtl("900");
      setOneTimeToken(data.token);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Création du site partenaire impossible."),
  });

  const updatePartner = useMutation({
    mutationFn: (input: {
      id: string;
      name: string;
      site_url: string;
      default_ttl_seconds: number | null;
      notes: string;
    }) => {
      if (!csrf) throw new Error("Session expirée.");
      const { id, ...patch } = input;
      return api.updatePartnerSite(id, patch, csrf);
    },
    onSuccess: () => {
      setError(null);
      setEditingPartner(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Mise à jour du site partenaire impossible."),
  });

  const deletePartner = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.deletePartnerSite(id, csrf);
    },
    onSuccess: () => {
      setError(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Suppression du site partenaire impossible."),
  });

  const rotate = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.rotateIdentity(id, csrf);
    },
    onSuccess: (data) => {
      setError(null);
      setOneTimeToken(data.token);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Rotation impossible."),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.revokeIdentity(id, csrf);
    },
    onSuccess: () => {
      setError(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Révocation impossible."),
  });

  // The backend is the authority; this only keeps the UI honest.
  if (!canAdmin) {
    return (
      <div className="stack">
        <h1>Administration</h1>
        <p role="alert" className="alert alert-error">
          Accès refusé. Cette console est réservée aux rôles opérateur et
          administrateur.
        </p>
      </div>
    );
  }

  const appNames = new Map(
    (applications.data?.items ?? []).map((a) => [a.id, a.name]),
  );
  const spaceNames = new Map(
    (spaces.data?.items ?? []).map((s) => [s.id, s.name]),
  );
  const appItems = applications.data?.items ?? [];
  const spaceItems = spaces.data?.items ?? [];
  const bucketItems: BucketListedItem[] = buckets.data?.items ?? [];

  const objectsByStatus = stats.data?.objects_by_status ?? {};
  const objectsTotal = Object.values(objectsByStatus).reduce((a, b) => a + b, 0);

  return (
    <div className="stack admin-page">
      <div className="page-head">
        <h1>Administration</h1>
      </div>
      <div role="tablist" aria-label="Rubriques de l'administration" className="tabs">
        {ADMIN_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`admin-tab-${item.id}`}
            aria-selected={tab === item.id}
            tabIndex={tab === item.id ? 0 : -1}
            className="tab"
            onClick={() => selectTab(item.id)}
            onKeyDown={(event) => {
              const step =
                event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
              if (step === 0) return;
              event.preventDefault();
              const index = ADMIN_TABS.findIndex((entry) => entry.id === item.id);
              const next = ADMIN_TABS[(index + step + ADMIN_TABS.length) % ADMIN_TABS.length];
              if (next) {
                selectTab(next.id);
                document.getElementById(`admin-tab-${next.id}`)?.focus();
              }
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <p className="muted">
        Applications, espaces, buckets et identités machine-à-machine.
        {canWrite
          ? " Votre rôle peut créer, modifier, activer/désactiver, faire tourner et révoquer."
          : " Lecture seule (les mutations exigent le rôle administrateur)."}
      </p>

      {error ? (
        <p role="alert" className="alert alert-error">
          {error}
          <button
            type="button"
            className="btn btn-ghost btn-small"
            onClick={() => setError(null)}
          >
            Fermer
          </button>
        </p>
      ) : null}

      {oneTimeToken ? (
        <OneTimeToken token={oneTimeToken} onDismiss={() => setOneTimeToken(null)} />
      ) : null}

      <section
        className="section"
        aria-labelledby="admin-stats-title"
        hidden={tab !== "overview"}
      >
        <div className="section-head">
          <h2 id="admin-stats-title">Tableau de bord</h2>
          {canWrite ? (
            <ConfirmAction
              label="Réconcilier les envois expirés"
              title="Réconcilier"
              message="Les intentions d'envoi en attente trop anciennes seront expirées et leurs octets partiels supprimés."
              confirmLabel="Réconcilier"
              pending={reconcile.isPending}
              onConfirm={() => reconcile.mutate()}
            />
          ) : null}
        </div>
        {reconcile.isSuccess ? (
          <p role="status" className="alert alert-ok">
            Réconciliation : {reconcile.data.expired} expiré(s),{" "}
            {reconcile.data.storage_deletes_attempted} suppression(s) stockage
            tentée(s)
            {reconcile.data.storage_failures
              ? `, ${reconcile.data.storage_failures} échec(s) stockage (réessayer plus tard)`
              : ""}
            .
          </p>
        ) : null}
        {stats.isError ? (
          <LoadError
            message="Statistiques indisponibles."
            error={stats.error}
            retrying={stats.isFetching}
            onRetry={() => void stats.refetch()}
          />
        ) : stats.isPending ? (
          <div className="stat-grid skeleton" role="status" aria-label="Chargement des statistiques">
            <span className="visually-hidden">Chargement…</span>
            {Array.from({ length: 5 }).map((_, index) => (
              <div className="stat" key={index} aria-hidden="true">
                <div className="skeleton-bar" style={{ height: 28 }} />
                <div className="skeleton-bar" style={{ marginTop: 8 }} />
              </div>
            ))}
          </div>
        ) : (
          <>
            <div className="stat-grid">
              <div className="stat">
                <div className="value">{objectsTotal}</div>
                <div className="label">Objets</div>
              </div>
              <div className="stat">
                <div className="value">{stats.data?.applications ?? 0}</div>
                <div className="label">Applications</div>
              </div>
              <div className="stat">
                <div className="value">{stats.data?.spaces ?? 0}</div>
                <div className="label">Espaces</div>
              </div>
              <div className="stat">
                <div className="value">{stats.data?.buckets ?? 0}</div>
                <div className="label">Buckets</div>
              </div>
              <div className="stat">
                <div className="value">
                  {stats.data?.active_service_identities ?? 0}
                  <span className="muted">
                    {" "}
                    / {stats.data?.service_identities ?? 0}
                  </span>
                </div>
                <div className="label">Identités actives</div>
              </div>
            </div>
            {Object.keys(objectsByStatus).length > 0 ? (
              <p className="muted">
                Objets par état :{" "}
                {Object.entries(objectsByStatus).map(([status, count]) => (
                  <span key={status} className="chip chip-muted">
                    {OBJECT_STATUS_LABELS[status] ?? status} : {count}
                  </span>
                ))}
              </p>
            ) : null}
          </>
        )}
      </section>

      <section
        className="section"
        aria-labelledby="admin-usage-title"
        hidden={tab !== "overview"}
      >
        <div className="section-head">
          <h2 id="admin-usage-title">Consommation</h2>
        </div>
        <p className="muted">
          Stockage réel du catalogue (objets vérifiés). Le trafic est une
          <strong> estimation</strong> : AURA ne proxifie pas les octets, donc
          chaque intention de téléchargement/aperçu et chaque ouverture de
          partage compte la taille de l'objet une fois. Les quotas sont
          mensuels (UTC) ; vide = aucun quota.
        </p>
        {usage.isError ? (
          <LoadError
            message="Consommation indisponible."
            error={usage.error}
            retrying={usage.isFetching}
            onRetry={() => void usage.refetch()}
          />
        ) : usage.isPending ? (
          <Loading label="Calcul de la consommation" />
        ) : (
          <>
            <div className="stat-grid">
              <div className="stat">
                <div className="value">{formatBytes(usage.data.totals.stored_bytes)}</div>
                <div className="label">Octets vérifiés</div>
              </div>
              <div className="stat">
                <div className="value">{usage.data.totals.available_count}</div>
                <div className="label">Objets disponibles</div>
              </div>
              <div className="stat">
                <div className="value">{formatBytes(usage.data.limits.max_object_bytes)}</div>
                <div className="label">Plafond par objet</div>
              </div>
              <div className="stat">
                <div className="value">{formatBytes(usage.data.totals.egress_bytes_month)}</div>
                <div className="label">Trafic estimé ({usage.data.period})</div>
              </div>
              <div className="stat">
                <div className="value">{usage.data.limits.max_pending_intents}</div>
                <div className="label">Envois en attente max</div>
              </div>
            </div>
            <p className="muted">
              Mesuré à {formatTs(usage.data.measured_at)} — les intentions en
              attente ne portent aucun octet engagé.
            </p>
            {usage.data.capacity ? (
              <p
                className={
                  usage.data.capacity.free_for_uploads_bytes <
                  usage.data.capacity.capacity_bytes / 20
                    ? "alert alert-error"
                    : "muted"
                }
                data-testid="capacity"
              >
                Capacité : {formatBytes(usage.data.capacity.stored_bytes)} stockés et{" "}
                {formatBytes(usage.data.capacity.reserved_bytes)} réservés par des envois en
                cours, sur {formatBytes(usage.data.capacity.capacity_bytes)}. Les nouveaux
                envois sont refusés au-delà de {usage.data.capacity.high_watermark_pct} % :
                encore {formatBytes(usage.data.capacity.free_for_uploads_bytes)} disponibles.
              </p>
            ) : (
              <p className="muted" data-testid="capacity">
                Aucune capacité configurée (AURA_STORAGE_CAPACITY_BYTES) : le remplissage du
                disque n'est pas surveillé.
              </p>
            )}
            {usage.data.spaces.length > 0 ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>Espace</th>
                    <th>Application</th>
                    <th>Stockage / quota</th>
                    <th>Trafic du mois / quota</th>
                    <th>Objets dispo.</th>
                    <th>En attente</th>
                  </tr>
                </thead>
                <tbody>
                  {usage.data.spaces.map((entry) => {
                    const storageChip = quotaChip(
                      quotaPct(entry.stored_bytes, entry.quota.storage_bytes),
                    );
                    const egressChip = quotaChip(
                      quotaPct(
                        entry.month.egress_bytes,
                        entry.quota.egress_bytes_monthly,
                      ),
                    );
                    return (
                      <tr key={entry.space_id}>
                        <td>
                          {entry.space_name}{" "}
                          <span className="muted">({entry.environment})</span>
                        </td>
                        <td>{entry.application_name ?? "—"}</td>
                        <td className="num">
                          {formatBytes(entry.stored_bytes)}
                          {entry.quota.storage_bytes !== null ? (
                            <span className="table-sub muted">
                              quota {formatBytes(entry.quota.storage_bytes)}{" "}
                              {storageChip ? (
                                <span className={storageChip.className}>
                                  {storageChip.label}
                                </span>
                              ) : null}
                            </span>
                          ) : (
                            <span className="table-sub muted">sans quota</span>
                          )}
                        </td>
                        <td className="num">
                          {formatBytes(entry.month.egress_bytes)}
                          <span className="table-sub muted">
                            {entry.quota.egress_bytes_monthly !== null
                              ? `quota ${formatBytes(entry.quota.egress_bytes_monthly)} `
                              : "sans quota · "}
                            {egressChip ? (
                              <span className={egressChip.className}>
                                {egressChip.label}
                              </span>
                            ) : null}
                          </span>
                        </td>
                        <td className="num">{entry.available_count}</td>
                        <td className="num">{entry.pending_count}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p className="muted">Aucun espace enregistré.</p>
            )}
          </>
        )}
      </section>

      <section
        className="section"
        aria-labelledby="admin-health-title"
        hidden={tab !== "overview"}
      >
        <div className="section-head">
          <h2 id="admin-health-title">Supervision</h2>
        </div>
        {health.isError ? (
          <LoadError
            message="Supervision indisponible."
            error={health.error}
            retrying={health.isFetching}
            onRetry={() => void health.refetch()}
          />
        ) : health.isPending ? (
          <Loading label="Vérification des services (base, stockage, disque)"
            slowHint="Le stockage met du temps à répondre ; le résultat s'affichera dès qu'il aura répondu ou abandonné." />
        ) : (
          <>
            <p role="status">
              État global :{" "}
              <span
                className={
                  health.data.status === "ok" ? "chip chip-ok" : "chip chip-warn"
                }
              >
                {health.data.status === "ok" ? "Nominal" : "Dégradé"}
              </span>
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>Composant</th>
                  <th>État</th>
                  <th>Détail</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(health.data.components).map(([name, component]) => (
                  <tr key={name}>
                    <td>
                      {name === "api"
                        ? "API"
                        : name === "database"
                          ? "Base catalogue"
                          : name === "storage"
                            ? "Stockage S3"
                            : name === "disk"
                              ? "Disque local"
                              : name}
                    </td>
                    <td>
                      <span
                        className={
                          component.status === "ok" ? "chip chip-ok" : "chip chip-warn"
                        }
                      >
                        {component.status === "ok" ? "OK" : "En panne"}
                      </span>
                    </td>
                    <td className="muted">
                      {healthDetail(component, formatBytes)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="callout">{frenchNote(health.data.note)}</p>
            <div className="section-head">
              <h3>Candidats orphelins</h3>
              <button
                type="button"
                className="btn btn-ghost btn-small"
                disabled={orphans.isFetching}
                onClick={() => void orphans.refetch()}
              >
                {orphans.isFetching ? "Analyse…" : "Analyser"}
              </button>
            </div>
            <p className="muted">
              Objets « disponibles » introuvables au stockage (lecture seule —
              rien n'est jamais supprimé sur ce signal : une panne transitoire
              produit les mêmes candidats).
            </p>
            {orphans.isError ? (
              <LoadError
                message="Analyse des orphelins indisponible."
                error={orphans.error}
                retrying={orphans.isFetching}
                onRetry={() => void orphans.refetch()}
              />
            ) : orphans.isPending ? (
              <Loading label="Recherche des fichiers introuvables au stockage"
                slowHint="L'analyse interroge chaque fichier ; cela peut prendre un moment." />
            ) : orphans.data.candidates.length === 0 ? (
              <p className="muted">
                Aucun candidat sur {orphans.data.checked} objet(s) vérifié(s).
              </p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Objet</th>
                    <th>Espace</th>
                    <th>Vérifié à</th>
                  </tr>
                </thead>
                <tbody>
                  {orphans.data.candidates.map((candidate) => (
                    <tr key={candidate.id}>
                      <td>
                        {candidate.display_name}{" "}
                        <span className="muted">({candidate.id.slice(0, 8)}…)</span>
                      </td>
                      <td className="muted">
                        {spaceNames.get(candidate.space_id) ?? candidate.space_id.slice(0, 8)}
                      </td>
                      <td className="muted">{formatTs(orphans.data.checked_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {health.data.recent_errors.events.length > 0 ? (
              <>
                <h3>Erreurs récentes</h3>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Action</th>
                      <th>Acteur</th>
                      <th>Résultat</th>
                    </tr>
                  </thead>
                  <tbody>
                    {health.data.recent_errors.events.map((event, index) => (
                      <tr key={`${event.ts}-${index}`}>
                        <td className="muted">{formatTs(event.ts)}</td>
                        <td>
                          <code>{event.action}</code>
                        </td>
                        <td>
                          <span title={actorLabel(event.actor).title}>
                            {actorLabel(event.actor).text}
                          </span>
                        </td>
                        <td>
                          <span className="chip chip-warn">{resultLabel(event.result)}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : (
              <p className="muted">
                Aucune erreur sur les dernières{" "}
                {Math.round(health.data.recent_errors.window_s / 60)} minutes.
              </p>
            )}
          </>
        )}
      </section>

      <section
        className="section"
        aria-labelledby="admin-storage-orphans-title"
        hidden={tab !== "overview"}
      >
        <div className="section-head">
          <h2 id="admin-storage-orphans-title">Octets non référencés</h2>
          <button
            type="button"
            className="btn btn-ghost btn-small"
            disabled={storageOrphans.isFetching}
            onClick={() => void storageOrphans.refetch()}
          >
            {storageOrphans.isFetching ? "Analyse…" : "Analyser le stockage"}
          </button>
        </div>
        <p className="muted">
          Fichiers présents au stockage sans fiche au catalogue, octets laissés par des
          envois abandonnés et envois en plusieurs parties orphelins. La corbeille n'en
          fait pas partie. Lecture seule : rien n'est supprimé depuis cet écran.
        </p>
        {storageOrphans.isError ? (
          <p role="alert" className="alert alert-error">
            Analyse du stockage indisponible.
          </p>
        ) : storageOrphans.data ? (
          <ul className="plain-list" data-testid="storage-orphans">
            {storageOrphans.data.buckets.map((entry) => (
              <li key={entry.bucket}>
                <strong>{entry.bucket}</strong> :{" "}
                {entry.error
                  ? "stockage indisponible"
                  : `${entry.orphans?.length ?? 0} fichier(s) non référencé(s) (${formatBytes(
                      entry.orphan_bytes ?? 0,
                    )}), ${entry.stale_uploads?.length ?? 0} envoi(s) en parties abandonné(s) sur ${
                      entry.scanned ?? 0
                    } objet(s) analysé(s)${entry.next_start_after ? " — analyse partielle" : ""}`}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section
        className="section"
        aria-labelledby="admin-integrity-title"
        hidden={tab !== "overview"}
      >
        <div className="section-head">
          <h2 id="admin-integrity-title">Intégrité des fichiers</h2>
        </div>
        {integrity.isError ? (
          <p role="alert" className="alert alert-error">
            Rapport d'intégrité indisponible.
          </p>
        ) : integrity.isPending ? (
          <p className="muted">Chargement…</p>
        ) : (
          <>
            {(() => {
              const ok = integrity.data.results.ok?.count ?? 0;
              const unchecked = integrity.data.results.unchecked?.count ?? 0;
              const bad =
                (integrity.data.results.mismatch?.count ?? 0) +
                (integrity.data.results.missing?.count ?? 0);
              return (
                <div className="stat-grid stat-grid-integrity" aria-hidden="true">
                  <div className={ok > 0 ? "stat stat-ok" : "stat"}>
                    <span className="value">{ok}</span>
                    <span className="label">Intacts</span>
                  </div>
                  <div className="stat">
                    <span className="value">{unchecked}</span>
                    <span className="label">Pas encore relus</span>
                  </div>
                  <div className={bad > 0 ? "stat stat-danger" : "stat"}>
                    <span className="value">{bad}</span>
                    <span className="label">En défaut</span>
                  </div>
                </div>
              );
            })()}
            <p className="muted" data-testid="integrity-summary">
              Chaque fichier est relu et son SHA-256 recalculé au moins tous les{" "}
              {integrity.data.interval_days} jours :{" "}
              {integrity.data.results.ok?.count ?? 0} intact(s),{" "}
              {integrity.data.results.unchecked?.count ?? 0} pas encore relu(s),{" "}
              {(integrity.data.results.mismatch?.count ?? 0) +
                (integrity.data.results.missing?.count ?? 0)}{" "}
              en défaut.
            </p>
            {integrity.data.problems.length > 0 ? (
              <>
                <p role="alert" className="alert alert-error">
                  Des fichiers ne correspondent plus à leur empreinte vérifiée ou ont
                  disparu du stockage : restaurez-les depuis la sauvegarde.
                </p>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Objet</th>
                      <th>Espace</th>
                      <th>Constat</th>
                      <th>Relu le</th>
                    </tr>
                  </thead>
                  <tbody>
                    {integrity.data.problems.map((problem) => (
                      <tr key={problem.id}>
                        <td>
                          {problem.display_name}{" "}
                          <span className="muted">({problem.id.slice(0, 8)}…)</span>
                        </td>
                        <td className="muted">
                          {spaceNames.get(problem.space_id) ?? problem.space_id.slice(0, 8)}
                        </td>
                        <td>
                          {problem.scrub_result === "missing"
                            ? "Absent du stockage"
                            : "Contenu altéré"}
                        </td>
                        <td className="muted">{formatTs(problem.scrubbed_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : null}
          </>
        )}
      </section>

      <section
        className="section"
        aria-labelledby="admin-audit-title"
        hidden={tab !== "audit"}
      >
        <div className="section-head">
          <h2 id="admin-audit-title">Journal d'audit</h2>
          {canWrite ? (
            <ConfirmAction
              label="Purger le journal"
              title="Purger le journal"
              message="Les événements plus anciens que la fenêtre de rétention seront supprimés. Les lignes sans horodatage valide sont conservées."
              confirmLabel="Purger"
              pending={pruneAudit.isPending}
              onConfirm={() => pruneAudit.mutate()}
            />
          ) : null}
        </div>
        <p className="muted">
          Recherche du plus récent au plus ancien. Ni mots de passe, ni
          secrets, ni URL présignées n'y figurent. Rétention :{" "}
          {auditSearch.data?.retention_days ?? "—"} jours.
        </p>
        {pruneAudit.isSuccess ? (
          <p role="status" className="alert alert-ok">
            Purge : {pruneAudit.data.kept} conservé(s), {pruneAudit.data.dropped}{" "}
            supprimé(s).
          </p>
        ) : null}
        <form
          className="form form-inline"
          onSubmit={(e) => {
            e.preventDefault();
            setAuditOffset(0);
            setAuditApplied({
              ...(auditActor.trim() ? { actor: auditActor.trim() } : {}),
              ...(auditAction.trim() ? { action: auditAction.trim() } : {}),
              ...(auditResult.trim() ? { result: auditResult.trim() } : {}),
              ...(auditSpace.trim() ? { spaceId: auditSpace.trim() } : {}),
              ...(auditRequest.trim() ? { requestId: auditRequest.trim() } : {}),
            });
          }}
        >
          <label className="field">
            <span>Acteur</span>
            <input
              type="text"
              value={auditActor}
              maxLength={200}
              placeholder="utilisateur ou identité"
              onChange={(e) => setAuditActor(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Action</span>
            <input
              type="text"
              value={auditAction}
              maxLength={100}
              placeholder="upload-intent, login…"
              onChange={(e) => setAuditAction(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Résultat</span>
            <input
              type="text"
              value={auditResult}
              maxLength={50}
              placeholder="success, failure…"
              onChange={(e) => setAuditResult(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Espace (id)</span>
            <input
              type="text"
              value={auditSpace}
              maxLength={64}
              placeholder="UUID de l'espace"
              onChange={(e) => setAuditSpace(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Requête (X-Request-Id)</span>
            <input
              type="text"
              value={auditRequest}
              maxLength={128}
              placeholder="identifiant de requête"
              onChange={(e) => setAuditRequest(e.target.value)}
            />
          </label>
          <div className="dialog-actions">
            <button type="submit" className="btn btn-primary">
              Rechercher
            </button>
          </div>
        </form>
        {auditSearch.isError ? (
          <LoadError
            message="Journal indisponible."
            error={auditSearch.error}
            retrying={auditSearch.isFetching}
            onRetry={() => void auditSearch.refetch()}
          />
        ) : auditSearch.isPending ? (
          <Loading label="Chargement du journal d'audit" />
        ) : auditSearch.data.items.length === 0 ? (
          <p className="muted">Aucun événement pour ces critères.</p>
        ) : (
          <>
            <table className="table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Action</th>
                  <th>Acteur</th>
                  <th>Résultat</th>
                  <th>Requête</th>
                </tr>
              </thead>
              <tbody>
                {auditSearch.data.items.map((event, index) => (
                  <tr key={`${event.ts}-${index}`}>
                    <td className="muted">{formatTs(event.ts)}</td>
                    <td>
                      <code>{event.action}</code>
                    </td>
                    <td>
                          <span title={actorLabel(event.actor).title}>
                            {actorLabel(event.actor).text}
                          </span>
                        </td>
                    <td>
                      <span
                        className={
                          event.result === "success" ? "chip chip-ok" : "chip chip-warn"
                        }
                      >
                        {resultLabel(event.result)}
                      </span>
                    </td>
                    <td className="muted">
                      {event.request_id ? (
                        <code>{String(event.request_id).slice(0, 8)}…</code>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              {auditSearch.data.total} événement(s) — page{" "}
              {Math.floor(auditOffset / AUDIT_PAGE_SIZE) + 1}
              {auditSearch.data.truncated
                ? " · historique ancien au-delà de la fenêtre de lecture"
                : ""}
              .
            </p>
            <div className="dialog-actions">
              <button
                type="button"
                className="btn"
                disabled={auditOffset === 0}
                onClick={() =>
                  setAuditOffset(Math.max(0, auditOffset - AUDIT_PAGE_SIZE))
                }
              >
                Page précédente
              </button>
              <button
                type="button"
                className="btn"
                disabled={auditOffset + AUDIT_PAGE_SIZE >= auditSearch.data.total}
                onClick={() => setAuditOffset(auditOffset + AUDIT_PAGE_SIZE)}
              >
                Page suivante
              </button>
            </div>
          </>
        )}
      </section>

      <section
        className="section"
        aria-labelledby="admin-apps-title"
        hidden={tab !== "apps"}
      >
        <h2 id="admin-apps-title">Applications</h2>
        {canWrite ? (
          <form
            className="form form-inline"
            onSubmit={(e) => {
              e.preventDefault();
              createApp.mutate(appName.trim());
            }}
          >
            <label className="field">
              <span>Nouvelle application</span>
              <input
                type="text"
                value={appName}
                maxLength={63}
                onChange={(e) => setAppName(e.target.value)}
                required
              />
            </label>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={createApp.isPending || appName.trim().length === 0}
            >
              Créer
            </button>
          </form>
        ) : null}
        {applications.isError ? (
          <LoadError
            message="Applications indisponibles."
            error={applications.error}
            retrying={applications.isFetching}
            onRetry={() => void applications.refetch()}
          />
        ) : applications.isPending ? (
          <Loading label="Chargement des applications" />
        ) : (applications.data?.items.length ?? 0) === 0 ? (
          <p className="empty">Aucune application.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Nom</th>
                  <th scope="col">Statut</th>
                  <th scope="col">Identifiant stable</th>
                  {canWrite ? (
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {applications.data?.items.map((a) => {
                  const state = lifecycleState(a.status);
                  const disabled = a.status !== "active";
                  return (
                    <tr key={a.id}>
                      <td className="name">{a.name}</td>
                      <td>
                        <span className={state.className}>{state.label}</span>
                      </td>
                      <td className="num muted">{a.id}</td>
                      {canWrite ? (
                        <td className="row-actions">
                          <button
                            type="button"
                            className="btn btn-small"
                            onClick={() => setEditingApp(a)}
                          >
                            Modifier
                          </button>
                          <ConfirmAction
                            label={disabled ? "Activer" : "Désactiver"}
                            title={disabled ? "Activer" : "Désactiver"}
                            message={
                              disabled ? (
                                <>
                                  Réactiver <strong>{a.name}</strong> ? De
                                  nouveaux espaces pourront lui être rattachés.
                                </>
                              ) : (
                                <>
                                  Désactiver <strong>{a.name}</strong> ? Aucun
                                  nouvel espace ne pourra lui être rattaché. Les
                                  espaces et données existants restent lisibles.
                                </>
                              )
                            }
                            confirmLabel={disabled ? "Activer" : "Désactiver"}
                            className="btn btn-small"
                            pending={setAppStatus.isPending}
                            onConfirm={() =>
                              setAppStatus.mutate({
                                id: a.id,
                                status: disabled ? "active" : "disabled",
                              })
                            }
                          />
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section
        className="section"
        aria-labelledby="admin-spaces-title"
        hidden={tab !== "apps"}
      >
        <h2 id="admin-spaces-title">Espaces</h2>
        {canWrite ? (
          <form
            className="form form-inline"
            onSubmit={(e) => {
              e.preventDefault();
              createSpace.mutate();
            }}
          >
            <label className="field">
              <span>Application</span>
              <select
                value={spaceApp}
                onChange={(e) => setSpaceApp(e.target.value)}
                required
              >
                <option value="">— choisir —</option>
                {appItems
                  .filter((a) => a.status === "active")
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </label>
            <label className="field">
              <span>Nom</span>
              <input
                type="text"
                value={spaceName}
                maxLength={63}
                onChange={(e) => setSpaceName(e.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>Environnement</span>
              <input
                type="text"
                value={spaceEnv}
                maxLength={32}
                onChange={(e) => setSpaceEnv(e.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>Bucket (optionnel)</span>
              <input
                type="text"
                value={spaceBucket}
                maxLength={63}
                onChange={(e) => setSpaceBucket(e.target.value)}
              />
            </label>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={
                createSpace.isPending ||
                appItems.filter((a) => a.status === "active").length === 0 ||
                spaceName.trim().length === 0 ||
                spaceEnv.trim().length === 0
              }
            >
              Créer l'espace
            </button>
          </form>
        ) : null}
        {spaces.isError ? (
          <LoadError
            message="Espaces indisponibles."
            error={spaces.error}
            retrying={spaces.isFetching}
            onRetry={() => void spaces.refetch()}
          />
        ) : spaces.isPending ? (
          <Loading label="Chargement des espaces" />
        ) : (spaces.data?.items.length ?? 0) === 0 ? (
          <p className="empty">Aucun espace.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Nom</th>
                  <th scope="col">Environnement</th>
                  <th scope="col">Application</th>
                  <th scope="col">Statut</th>
                  <th scope="col">Identifiant stable</th>
                  {canWrite ? (
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {spaces.data?.items.map((s) => {
                  const state = lifecycleState(s.status);
                  const disabled = s.status !== "active";
                  return (
                    <tr key={s.id}>
                      <td className="name">{s.name}</td>
                      <td className="muted">{s.environment}</td>
                      <td className="muted">
                        {appNames.get(s.application_id) ?? s.application_id}
                      </td>
                      <td>
                        <span className={state.className}>{state.label}</span>
                      </td>
                      <td className="num muted">{s.id}</td>
                      {canWrite ? (
                        <td className="row-actions">
                          <button
                            type="button"
                            className="btn btn-small"
                            onClick={() => setEditingSpace(s)}
                          >
                            Modifier
                          </button>
                          <button
                            type="button"
                            className="btn btn-small"
                            onClick={() => setEditingQuotas(s)}
                          >
                            Quotas
                          </button>
                          <ConfirmAction
                            label={disabled ? "Activer" : "Désactiver"}
                            title={disabled ? "Activer" : "Désactiver"}
                            message={
                              disabled ? (
                                <>
                                  Réactiver l'espace <strong>{s.name}</strong> ?
                                  Les envois et la création d'identités seront de
                                  nouveau autorisés.
                                </>
                              ) : (
                                <>
                                  Désactiver l'espace <strong>{s.name}</strong> ?
                                  Les nouveaux envois et la création d'identités
                                  seront refusés. Les objets existants restent
                                  lisibles et téléchargeables.
                                </>
                              )
                            }
                            confirmLabel={disabled ? "Activer" : "Désactiver"}
                            className="btn btn-small"
                            pending={setSpaceStatus.isPending}
                            onConfirm={() =>
                              setSpaceStatus.mutate({
                                id: s.id,
                                status: disabled ? "active" : "disabled",
                              })
                            }
                          />
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section
        className="section"
        aria-labelledby="admin-buckets-title"
        hidden={tab !== "buckets"}
      >
        <h2 id="admin-buckets-title">Buckets</h2>
        <p className="muted">
          Un bucket est rattaché à un espace. AURA ne conserve et n'affiche
          aucun identifiant ni secret d'accès S3 ; ceux-ci restent hors de la
          base. Les buckets ne sont jamais supprimés par l'interface.
        </p>
        {canWrite ? (
          <form
            className="form form-inline"
            onSubmit={(e) => {
              e.preventDefault();
              createBucket.mutate();
            }}
          >
            <label className="field">
              <span>Espace</span>
              <select
                value={bucketSpace}
                onChange={(e) => setBucketSpace(e.target.value)}
                required
              >
                <option value="">— choisir —</option>
                {spaceItems.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.environment})
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Nom du bucket</span>
              <input
                type="text"
                value={bucketName}
                maxLength={63}
                onChange={(e) => setBucketName(e.target.value)}
                placeholder="minuscules, chiffres, . et -"
                required
              />
            </label>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={
                createBucket.isPending ||
                spaceItems.length === 0 ||
                bucketSpace === "" ||
                bucketName.trim().length === 0
              }
            >
              Enregistrer le bucket
            </button>
          </form>
        ) : null}
        {buckets.isError ? (
          <LoadError
            message="Buckets indisponibles."
            error={buckets.error}
            retrying={buckets.isFetching}
            onRetry={() => void buckets.refetch()}
          />
        ) : buckets.isPending ? (
          <Loading label="Chargement des buckets" />
        ) : bucketItems.length === 0 ? (
          <p className="empty">Aucun bucket.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Bucket</th>
                  <th scope="col">Espace</th>
                  <th scope="col">Application</th>
                  <th scope="col">Environnement</th>
                  <th scope="col">Par défaut</th>
                  {canWrite ? (
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {bucketItems.map((b) => (
                  <tr key={b.id}>
                    <td className="name">{b.name}</td>
                    <td className="muted">{b.space_name ?? b.space_id}</td>
                    <td className="muted">
                      {b.application_name ?? b.application_id ?? "—"}
                    </td>
                    <td className="muted">{b.environment ?? "—"}</td>
                    <td>
                      <span
                        className={
                          b.is_default ? "chip chip-ok" : "chip chip-muted"
                        }
                      >
                        {b.is_default ? "Oui" : "Non"}
                      </span>
                    </td>
                    {canWrite ? (
                      <td className="row-actions">
                        <ConfirmAction
                          label="Définir par défaut"
                          title="Définir le bucket par défaut"
                          message={
                            <>
                              Faire de <strong>{b.name}</strong> le bucket par
                              défaut de l'espace{" "}
                              <strong>{b.space_name ?? b.space_id}</strong> ? Les
                              nouveaux envois sans bucket explicite y seront
                              déposés. Les objets existants ne changent pas.
                            </>
                          }
                          confirmLabel="Définir par défaut"
                          className="btn btn-small"
                          pending={setBucketDefault.isPending}
                          disabled={b.is_default}
                          onConfirm={() =>
                            setBucketDefault.mutate({ id: b.id, isDefault: true })
                          }
                        />
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section
        className="section"
        aria-labelledby="admin-identities-title"
        hidden={tab !== "identities"}
      >
        <h2 id="admin-identities-title">Identités machine-à-machine</h2>
        <p className="muted">
          Les jetons ne sont jamais réaffichés : AURA n'en conserve que
          l'empreinte SHA-256. Un jeton n'est visible qu'une seule fois, à sa
          création ou à sa rotation.
        </p>
        {canWrite ? (
          <form
            className="form form-inline"
            onSubmit={(e) => {
              e.preventDefault();
              createIdentity.mutate();
            }}
          >
            <label className="field">
              <span>Nom</span>
              <input
                type="text"
                value={idName}
                onChange={(e) => setIdName(e.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>Espace</span>
              <select
                value={idSpace}
                onChange={(e) => setIdSpace(e.target.value)}
                required
              >
                <option value="">— choisir —</option>
                {spaceItems.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.environment})
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="field scopes-field">
              <legend>Portées</legend>
              {SERVICE_SCOPES.map((scope) => (
                <label key={scope} className="checkbox">
                  <input
                    type="checkbox"
                    checked={idScopes.includes(scope)}
                    onChange={(e) =>
                      setIdScopes((current) =>
                        e.target.checked
                          ? [...current, scope]
                          : current.filter((s) => s !== scope),
                      )
                    }
                  />
                  {scope}
                </label>
              ))}
            </fieldset>
            <label className="field">
              <span>Expiration (jours, optionnel)</span>
              <input
                type="number"
                min="1"
                value={idTtlDays}
                onChange={(e) => setIdTtlDays(e.target.value)}
              />
            </label>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={
                createIdentity.isPending || spaceItems.length === 0 || idScopes.length === 0
              }
            >
              Créer l'identité
            </button>
          </form>
        ) : null}
        {identities.isError ? (
          <LoadError
            message="Identités indisponibles."
            error={identities.error}
            retrying={identities.isFetching}
            onRetry={() => void identities.refetch()}
          />
        ) : identities.isPending ? (
          <Loading label="Chargement des identités" />
        ) : (identities.data?.items.length ?? 0) === 0 ? (
          <p className="empty">Aucune identité de service.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Nom</th>
                  <th scope="col">Espace</th>
                  <th scope="col">Portées</th>
                  <th scope="col">État</th>
                  <th scope="col">Expire</th>
                  {canWrite ? (
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {identities.data?.items.map((i) => {
                  const state = identityState(i);
                  const revoked = Boolean(i.revoked_at);
                  return (
                    <tr key={i.id}>
                      <td className="name">{i.name}</td>
                      <td className="muted">
                        {spaceNames.get(i.space_id) ?? i.space_id}
                      </td>
                      <td className="muted">{i.scopes.join(", ") || "—"}</td>
                      <td>
                        <span className={state.className}>{state.label}</span>
                      </td>
                      <td className="num muted">{formatTs(i.expires_at)}</td>
                      {canWrite ? (
                        <td className="row-actions">
                          <ConfirmAction
                            label="Rotation"
                            title="Faire tourner le jeton"
                            message={
                              <>
                                Générer un nouveau jeton pour{" "}
                                <strong>{i.name}</strong> ? L'ancien cesse
                                immédiatement de fonctionner.
                              </>
                            }
                            confirmLabel="Rotation"
                            className="btn btn-small"
                            pending={rotate.isPending}
                            disabled={revoked}
                            onConfirm={() => rotate.mutate(i.id)}
                          />
                          <ConfirmAction
                            label="Révoquer"
                            title="Révoquer l'identité"
                            message={
                              <>
                                Révoquer <strong>{i.name}</strong> ? Toute
                                authentification avec ce jeton échouera.
                              </>
                            }
                            confirmLabel="Révoquer"
                            danger
                            className="btn btn-small"
                            pending={revoke.isPending}
                            disabled={revoked}
                            onConfirm={() => revoke.mutate(i.id)}
                          />
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section
        className="panel"
        aria-labelledby="admin-partners-title"
        hidden={tab !== "partners"}
      >
        <h2 id="admin-partners-title">Intégrations partenaires</h2>
        <p className="muted">
          Un site partenaire consomme un espace avec sa propre clé de service.
          L'URL permanente reste chez le partenaire
          (<span className="mono">https://son-site/media/&lt;oid&gt;</span>) ; AURA
          ne fournit que la clé et la durée de signature conseillée. La clé n'est
          affichée qu'une fois, à la création ou à la rotation.
        </p>
        {canWrite ? (
          <form
            className="form form-inline"
            onSubmit={(e) => {
              e.preventDefault();
              createPartner.mutate();
            }}
          >
            <label className="field">
              <span>Nom du site</span>
              <input
                type="text"
                value={partnerName}
                onChange={(e) => setPartnerName(e.target.value)}
                placeholder="Cours Next.js"
                required
              />
            </label>
            <label className="field">
              <span>Origine (https)</span>
              <input
                type="url"
                value={partnerUrl}
                onChange={(e) => setPartnerUrl(e.target.value)}
                placeholder="https://cours.example.com"
                required
              />
            </label>
            <label className="field">
              <span>Espace</span>
              <select
                value={partnerSpace}
                onChange={(e) => setPartnerSpace(e.target.value)}
                required
              >
                <option value="">— choisir —</option>
                {spaceItems.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.environment})
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="field scopes-field">
              <legend>Portées</legend>
              {SERVICE_SCOPES.map((scope) => (
                <label key={scope} className="checkbox">
                  <input
                    type="checkbox"
                    checked={partnerScopes.includes(scope)}
                    onChange={(e) =>
                      setPartnerScopes((current) =>
                        e.target.checked
                          ? [...current, scope]
                          : current.filter((s) => s !== scope),
                      )
                    }
                  />
                  {scope}
                </label>
              ))}
            </fieldset>
            <label className="field">
              <span>Expiration de la clé (jours, optionnel)</span>
              <input
                type="number"
                min="1"
                value={partnerTtlDays}
                onChange={(e) => setPartnerTtlDays(e.target.value)}
              />
            </label>
            <label className="field">
              <span>TTL média conseillé (secondes)</span>
              <input
                type="number"
                min="60"
                max="604800"
                value={partnerMediaTtl}
                onChange={(e) => setPartnerMediaTtl(e.target.value)}
              />
            </label>
            <label className="field">
              <span>Notes (optionnel)</span>
              <input
                type="text"
                value={partnerNotes}
                onChange={(e) => setPartnerNotes(e.target.value)}
                placeholder="Contrat, contact, périmètre…"
              />
            </label>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={
                createPartner.isPending ||
                spaceItems.length === 0 ||
                partnerScopes.length === 0
              }
            >
              Créer le site partenaire
            </button>
          </form>
        ) : null}
        {partnerSites.isError ? (
          <LoadError
            message="Intégrations indisponibles."
            error={partnerSites.error}
            retrying={partnerSites.isFetching}
            onRetry={() => void partnerSites.refetch()}
          />
        ) : partnerSites.isPending ? (
          <Loading label="Chargement des intégrations" />
        ) : (partnerSites.data?.items.length ?? 0) === 0 ? (
          <p className="empty">
            Aucun site partenaire. Créez-en un pour obtenir une clé dédiée et sa
            durée de signature conseillée.
          </p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Site</th>
                  <th scope="col">Espace</th>
                  <th scope="col">Clé</th>
                  <th scope="col">TTL média</th>
                  <th scope="col">Dernier appel</th>
                  {canWrite ? (
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {partnerSites.data?.items.map((site) => {
                  const state = partnerState(site);
                  const revoked = Boolean(site.identity.revoked_at);
                  return (
                    <tr key={site.id}>
                      <td className="name">
                        {site.name}
                        <span className="muted mono table-sub">
                          {site.site_url}/media/&lt;oid&gt;
                        </span>
                        {site.notes ? (
                          <span className="muted table-sub">{site.notes}</span>
                        ) : null}
                      </td>
                      <td className="muted">
                        {spaceNames.get(site.space_id) ?? site.space_id}
                      </td>
                      <td>
                        <span className={state.className}>{state.label}</span>
                        <span className="muted table-sub">
                          {site.identity.scopes.join(", ") || "—"}
                          {site.identity.expires_at
                            ? ` · expire ${formatTs(site.identity.expires_at)}`
                            : ""}
                        </span>
                      </td>
                      <td className="num muted">
                        {formatTtl(site.default_ttl_seconds)}
                      </td>
                      <td className="num muted">
                        {formatTs(site.identity.last_used_at)}
                      </td>
                      {canWrite ? (
                        <td className="row-actions">
                          <button
                            type="button"
                            className="btn btn-small"
                            onClick={() => {
                              void navigator.clipboard
                                .writeText(`${site.site_url}/media/`)
                                .then(() => {
                                  setError(null);
                                  setCopiedPartnerId(site.id);
                                })
                                .catch(() =>
                                  setError(
                                    "Copie impossible dans ce navigateur.",
                                  ),
                                );
                            }}
                          >
                            {copiedPartnerId === site.id
                              ? "Préfixe copié"
                              : "Copier l'URL"}
                          </button>
                          <button
                            type="button"
                            className="btn btn-small"
                            onClick={() => setEditingPartner(site)}
                          >
                            Modifier
                          </button>
                          <ConfirmAction
                            label="Rotation"
                            title="Faire tourner la clé"
                            message={
                              <>
                                Générer une nouvelle clé pour{" "}
                                <strong>{site.name}</strong> ? L'ancienne cesse
                                immédiatement de fonctionner ; le site devra être
                                redéployé avec la nouvelle.
                              </>
                            }
                            confirmLabel="Rotation"
                            className="btn btn-small"
                            pending={rotate.isPending}
                            disabled={revoked}
                            onConfirm={() => rotate.mutate(site.identity_id)}
                          />
                          <ConfirmAction
                            label="Révoquer"
                            title="Révoquer la clé"
                            message={
                              <>
                                Révoquer l'accès de <strong>{site.name}</strong> ?
                                Toute requête avec cette clé échouera
                                immédiatement.
                              </>
                            }
                            confirmLabel="Révoquer"
                            danger
                            className="btn btn-small"
                            pending={revoke.isPending}
                            disabled={revoked}
                            onConfirm={() => revoke.mutate(site.identity_id)}
                          />
                          <ConfirmAction
                            label="Supprimer"
                            title="Supprimer l'intégration"
                            message={
                              <>
                                Supprimer <strong>{site.name}</strong> ? Sa clé
                                sera révoquée immédiatement et l'entrée
                                disparaîtra de la console. L'historique d'audit
                                est conservé.
                              </>
                            }
                            confirmLabel="Supprimer"
                            danger
                            className="btn btn-small"
                            pending={deletePartner.isPending}
                            onConfirm={() => deletePartner.mutate(site.id)}
                          />
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {editingPartner ? (
        <EditPartnerDialog
          site={editingPartner}
          pending={updatePartner.isPending}
          onClose={() => setEditingPartner(null)}
          onSubmit={(patch) =>
            updatePartner.mutate({ id: editingPartner.id, ...patch })
          }
        />
      ) : null}

      {editingApp ? (
        <EditApplicationDialog
          application={editingApp}
          pending={updateApp.isPending}
          onClose={() => setEditingApp(null)}
          onSubmit={(name) => updateApp.mutate({ id: editingApp.id, name })}
        />
      ) : null}

      {editingQuotas ? (() => {
        const entry = usage.data?.spaces.find(
          (e) => e.space_id === editingQuotas.id,
        );
        return (
          <SpaceQuotasDialog
            space={editingQuotas}
            quota={
              entry?.quota ?? {
                storage_bytes: null,
                egress_bytes_monthly: null,
                updated_at: null,
                updated_by: null,
              }
            }
            storedBytes={entry?.stored_bytes ?? 0}
            egressBytes={entry?.month.egress_bytes ?? 0}
            pending={setSpaceQuotas.isPending}
            onClose={() => setEditingQuotas(null)}
            onSubmit={(input) =>
              setSpaceQuotas.mutate({ id: editingQuotas.id, ...input })
            }
          />
        );
      })() : null}

      {editingSpace ? (
        <EditSpaceDialog
          space={editingSpace}
          applicationName={
            appNames.get(editingSpace.application_id) ??
            editingSpace.application_id
          }
          pending={updateSpace.isPending}
          onClose={() => setEditingSpace(null)}
          onSubmit={(patch) =>
            updateSpace.mutate({ id: editingSpace.id, ...patch })
          }
        />
      ) : null}
    </div>
  );
}
