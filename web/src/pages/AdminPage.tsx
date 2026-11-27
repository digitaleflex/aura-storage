import { activeSpaces, frenchNote, healthDetail } from "../lib/adminText";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, hasAdminAccess, hasScope, SERVICE_SCOPES } from "../lib/api";
import type {
  ApplicationItem,
  AuditQuery,
  BucketListedItem,
  CoverApplyResult,
  CoverCandidate,
  CoverCandidateBook,
  CoverSearchInput,
  IdentityItem,
  ObjectReverifyResult,
  OrphanCleanupInput,
  OrphanCleanupResult,
  PartnerSite,
  SpaceItem,
  SpaceQuota,
  StorageOrphanReport,
} from "../lib/api";
import {
  applyOrphanCleanupResult,
  buildOrphanCleanupBatch,
  mergeStorageOrphanPage,
  type OrphanCleanupExclusions,
} from "../lib/adminMaintenance";
import { useAuth, useSession } from "../lib/auth";
import { ConfirmAction, Dialog } from "../components/Dialog";
import { OneTimeToken } from "../components/OneTimeToken";
import { PortalStats } from "../components/PortalStats";
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

/** Badge for a cover proposal: how confidently its metadata matched the book. */
function coverMatch(match: CoverCandidate["match"]): { label: string; className: string } {
  if (match === "exact") return { label: "Exact", className: "chip chip-ok" };
  if (match === "title") return { label: "Titre", className: "chip chip-muted" };
  return { label: "Approche", className: "chip chip-warn" };
}

/** Publication state of a book: a validated choice is not yet published. */
function coverState(book: CoverCandidateBook): { label: string; className: string } {
  if (book.status === "applied" || book.status === "already_applied") {
    return { label: "Couverture publiée", className: "chip chip-ok" };
  }
  if (book.chosen_url) {
    return { label: "Choix validé · à publier", className: "chip chip-warn" };
  }
  return { label: "Aucun choix", className: "chip chip-muted" };
}

type CoverThumbProps = {
  src?: string | null;
  title: string;
  alt: string;
  label?: string;
  className?: string;
  onClick?: () => void;
  onDoubleClick?: () => void;
};

/** Cover image with a typographic jacket when the artwork is absent or broken. */
function CoverThumb({
  src, title, alt, label, className = "", onClick, onDoubleClick,
}: CoverThumbProps) {
  const [broken, setBroken] = useState(false);
  const initial = (title || "Livre").trim().charAt(0).toUpperCase() || "L";
  const classes = `admin-cover-thumb ${className}`.trim();
  if (!src || broken) {
    return (
      <span
        className={`admin-cover-fallback ${className}`.trim()}
        role="img"
        aria-label={label || `Couverture indisponible pour ${title || "ce livre"}`}
        onClick={onClick}
        onDoubleClick={onDoubleClick}
        onKeyDown={onClick ? (event) => {
          if (event.key === "Enter" || event.key === " ") onClick();
        } : undefined}
        tabIndex={onClick ? 0 : undefined}
      >
        <span aria-hidden="true">{initial}</span>
      </span>
    );
  }
  return (
    <img
      className={classes}
      src={src}
      alt={alt}
      title={label}
      referrerPolicy="no-referrer"
      loading="lazy"
      width={64}
      height={80}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onError={() => setBroken(true)}
    />
  );
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

/** The reverify route reports a checksum mismatch as a structured HTTP 409. */
function isObjectReverifyResult(value: unknown): value is ObjectReverifyResult {
  if (typeof value !== "object" || value === null) return false;
  const result = value as Partial<ObjectReverifyResult>;
  return (
    typeof result.id === "string" &&
    (result.status === "available" || result.status === "suspect") &&
    typeof result.size_bytes === "number" &&
    typeof result.checksum_sha256 === "string"
  );
}

function orphanSkipReason(reason: string): string {
  const labels: Record<string, string> = {
    "outside the AURA prefix": "clé hors du préfixe AURA",
    "revision key": "clé d'une révision conservée",
    "now accounted for": "élément désormais référencé au catalogue",
    "not found or storage unavailable": "introuvable ou stockage indisponible",
    "too recent": "élément trop récent",
    "storage delete failed": "échec de suppression au stockage",
    "upload still active": "envoi multipart toujours actif",
    "abort failed or already gone": "abandon impossible ou déjà effectué",
  };
  return labels[reason] ?? reason;
}

const AUDIT_PAGE_SIZE = 50;
const TERMINAL_RECONCILE_LIMIT = 500;
const STORAGE_ORPHANS_QUERY_KEY = ["admin", "storage-orphans"] as const;
const STORAGE_ORPHANS_PAGE_SIZE = 5000;

/** Sections of the console, one tab each (labels are what the user reads). */
const ADMIN_TABS = [
  { id: "overview", label: "Vue d'ensemble" },
  { id: "audit", label: "Journal d'audit" },
  { id: "apps", label: "Applications et espaces" },
  { id: "buckets", label: "Buckets" },
  { id: "identities", label: "Identités de service" },
  { id: "partners", label: "Intégrations" },
  { id: "covers", label: "Couvertures" },
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
type AdminPageProps = { onlyCovers?: boolean };

export function AdminCoversPage() {
  return <AdminPage onlyCovers />;
}

export function AdminPage({ onlyCovers = false }: AdminPageProps) {
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
  // Cover validation: a missing entry means "keep the server's current choice";
  // an explicit "" means "do not apply", exactly like candidate_url: null.
  const [coverChoices, setCoverChoices] = useState<Record<string, string>>({});
  const [coverIsbns, setCoverIsbns] = useState<Record<string, string>>({});
  const [coverStatusFilter, setCoverStatusFilter] = useState("all");
  const [coverDryRun, setCoverDryRun] = useState(false);
  const [coverLimit, setCoverLimit] = useState(200);
  const [coverApplyResult, setCoverApplyResult] = useState<CoverApplyResult | null>(null);
  // Persistent outcome of the last cover action; replaced by the next one.
  const [coverMessage, setCoverMessage] = useState<string | null>(null);
  const [coverZoom, setCoverZoom] = useState<{
    url: string;
    title: string;
    author: string;
    provider: string;
    objectId: string;
    status: string;
    fallbackUrl?: string | null;
  } | null>(null);
  const coverClickTimer = useRef<number | null>(null);

  function openCoverZoom(zoom: NonNullable<typeof coverZoom>) {
    setCoverZoom(zoom);
  }

  function quickSelectCover(zoom: {
    objectId: string;
    url: string;
    title: string;
    status: string;
  }) {
    if (zoom.status === "applied" || zoom.status === "already_applied") {
      setCoverMessage(
        `« ${zoom.title} » possède déjà une couverture publiée. Utilisez « Remplacer la couverture » pour la modifier.`,
      );
      return;
    }
    if (!canWrite) {
      setCoverMessage("La validation exige le droit admin:write.");
      return;
    }
    setCoverZoom(null);
    setCoverChoices((current) => ({ ...current, [zoom.objectId]: zoom.url }));
    selectCover.mutate({ object_id: zoom.objectId, candidate_url: zoom.url });
  }
  const [reverifyResults, setReverifyResults] = useState<Record<string, ObjectReverifyResult>>({});
  const [orphanCleanupResults, setOrphanCleanupResults] = useState<
    Record<string, OrphanCleanupResult>
  >({});
  const [orphanCleanupExclusions, setOrphanCleanupExclusions] = useState<
    Record<string, OrphanCleanupExclusions>
  >({});

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
    queryKey: STORAGE_ORPHANS_QUERY_KEY,
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
  const coverCandidates = useQuery({
    queryKey: ["admin", "cover-candidates"],
    queryFn: () => api.adminCoverCandidates(),
    enabled: canAdmin,
    retry: false,
  });

  // A space deactivated in another tab must not remain silently selected in a
  // create-identity/partner form; the backend correctly refuses those writes.
  useEffect(() => {
    const activeIds = new Set(
      activeSpaces(spaces.data?.items).map((space) => space.id),
    );
    setIdSpace((current) => (current && !activeIds.has(current) ? "" : current));
    setPartnerSpace((current) => (current && !activeIds.has(current) ? "" : current));
  }, [spaces.data?.items]);

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

  /** Readable book name for a cover action's confirmation message. */
  function coverTitle(objectId: string, book?: CoverCandidateBook): string {
    return (
      book?.title ||
      book?.display_name ||
      coverCandidates.data?.books.find((item) => item.object_id === objectId)?.title ||
      objectId
    );
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

  const scrubIntegrity = useMutation({
    mutationFn: () => {
      if (!csrf) throw new Error("Session expirée.");
      return api.scrubIntegrity(csrf);
    },
    onSuccess: () => {
      setError(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Vérification d'intégrité impossible."),
  });

  const reverifyObject = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.reverifyObject(id, csrf);
    },
    onMutate: (id) => {
      setError(null);
      setReverifyResults((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
    },
    onSuccess: (result) => {
      setError(null);
      setReverifyResults((current) => ({ ...current, [result.id]: result }));
      refreshAdmin();
    },
    onError: (err, id) => {
      setReverifyResults((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      const payload = err instanceof ApiError ? err.payload : undefined;
      if (err instanceof ApiError && err.status === 409 && isObjectReverifyResult(payload)) {
        setError(null);
        setReverifyResults((current) => ({ ...current, [id]: payload }));
        refreshAdmin();
        return;
      }
      fail(err, "Re-vérification impossible.");
    },
  });

  const reconcileTerminal = useMutation({
    mutationFn: () => {
      if (!csrf) throw new Error("Session expirée.");
      return api.reconcileTerminal(csrf, TERMINAL_RECONCILE_LIMIT);
    },
    onSuccess: () => {
      setError(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Nettoyage des objets terminés impossible."),
  });

  const reconcileReverse = useMutation({
    mutationFn: (dryRun: boolean) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.reconcileReverse(csrf, dryRun);
    },
    onSuccess: () => {
      setError(null);
      refreshAdmin();
    },
    onError: (err) => fail(err, "Réconciliation inverse impossible."),
  });

  const cleanupStorageOrphans = useMutation({
    mutationFn: (input: OrphanCleanupInput) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.cleanupStorageOrphans(input, csrf);
    },
    onMutate: (input) => {
      setError(null);
      setOrphanCleanupResults((current) => {
        const next = { ...current };
        delete next[input.bucket];
        return next;
      });
      setOrphanCleanupExclusions((current) => {
        const previous = current[input.bucket] ?? { keys: new Set<string>(), uploads: new Set<string>() };
        return {
          ...current,
          [input.bucket]: {
            keys: new Set([...previous.keys, ...(input.keys ?? [])]),
            uploads: new Set([...previous.uploads, ...(input.uploads ?? []).map((upload) => upload.upload_id)]),
          },
        };
      });
    },
    onSuccess: (result, input) => {
      setError(null);
      setOrphanCleanupResults((current) => ({ ...current, [input.bucket]: result }));
      queryClient.setQueryData<StorageOrphanReport>(STORAGE_ORPHANS_QUERY_KEY, (current) =>
        current ? applyOrphanCleanupResult(current, input.bucket, result) : current,
      );
      refreshAdmin();
    },
    onError: (err, input) => {
      setOrphanCleanupResults((current) => {
        const next = { ...current };
        delete next[input.bucket];
        return next;
      });
      fail(err, "Nettoyage des orphelins impossible.");
    },
  });

  const loadMoreStorageOrphans = useMutation({
    mutationFn: async (input: { bucket: string; startAfter: string }) => {
      const report = await api.adminStorageOrphans({
        bucket: input.bucket,
        startAfter: input.startAfter,
        maxKeys: STORAGE_ORPHANS_PAGE_SIZE,
      });
      const page = report.buckets.find((entry) => entry.bucket === input.bucket);
      if (!page || page.error) throw new ApiError(502, "storage unavailable");
      return report;
    },
    onSuccess: (report) => {
      setError(null);
      queryClient.setQueryData<StorageOrphanReport>(STORAGE_ORPHANS_QUERY_KEY, (current) =>
        current ? mergeStorageOrphanPage(current, report) : report,
      );
    },
    onError: (err) => fail(err, "Chargement de la suite du scan impossible."),
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

  const searchCover = useMutation({
    mutationFn: (input: CoverSearchInput) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.searchCover(input, csrf);
    },
    onMutate: () => setCoverMessage(null),
    onSuccess: (result, input) => {
      setError(null);
      setCoverMessage(
        `Recherche terminée pour « ${coverTitle(input.object_id, result.book)} » : ${result.book.candidates.length} candidat(s).`,
      );
      refreshAdmin();
    },
    onError: (err) => fail(err, "Recherche de couverture impossible."),
  });

  const selectCover = useMutation({
    mutationFn: (input: { object_id: string; candidate_url: string | null }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.selectCover(input, csrf);
    },
    onMutate: () => setCoverMessage(null),
    onSuccess: (updated, input) => {
      setError(null);
      // Drop the local override: the refetched book now carries the choice.
      setCoverChoices((current) => {
        const next = { ...current };
        delete next[input.object_id];
        return next;
      });
      setCoverMessage(
        `Choix enregistré pour « ${coverTitle(input.object_id, updated.book)} » — couverture NON encore publiée. Utilisez « Appliquer les couvertures validées » ci-dessous.`,
      );
      refreshAdmin();
    },
    onError: (err) => fail(err, "Enregistrement du choix impossible."),
  });

  const clearCover = useMutation({
    mutationFn: (objectId: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.selectCover({ object_id: objectId, candidate_url: null }, csrf);
    },
    onMutate: () => setCoverMessage(null),
    onSuccess: (_updated, objectId) => {
      setError(null);
      setCoverChoices((current) => {
        const next = { ...current };
        delete next[objectId];
        return next;
      });
      setCoverMessage("Ancien choix effacé. Sélectionnez une nouvelle couverture.");
      refreshAdmin();
    },
    onError: (err) => fail(err, "Effacement du choix impossible."),
  });

  const applySelectedCovers = useMutation({
    mutationFn: (input: { dry_run: boolean; confirm: boolean; limit: number }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.applySelectedCovers(input, csrf);
    },
    onMutate: () => setCoverMessage(null),
    onSuccess: (result) => {
      setError(null);
      setCoverApplyResult(result);
      refreshAdmin();
    },
    onError: (err) => {
      setCoverApplyResult(null);
      fail(err, "Application des couvertures impossible.");
    },
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
  const activeSpaceItems = activeSpaces(spaceItems);
  const bucketItems: BucketListedItem[] = buckets.data?.items ?? [];

  const objectsByStatus = stats.data?.objects_by_status ?? {};
  const objectsTotal = Object.values(objectsByStatus).reduce((a, b) => a + b, 0);

  // Missing covers first, then alphabetical. Filtering is UI-only: the review
  // file order on disk is never changed by a display choice.
  const allCoverBooks = coverCandidates.data?.books ?? [];
  const coverStats = {
    total: allCoverBooks.length,
    published: allCoverBooks.filter((book) => Boolean(book.cover_url)).length,
    missing: allCoverBooks.filter((book) => !book.cover_url).length,
    toPublish: allCoverBooks.filter((book) => book.status === "selected").length,
  };
  const coverCoverage = coverStats.total
    ? Math.round((coverStats.published / coverStats.total) * 100)
    : 0;
  const visibleCoverBooks = allCoverBooks
    .filter((book) => {
      if (coverStatusFilter === "all") return true;
      if (coverStatusFilter === "missing") return !book.cover_url;
      if (coverStatusFilter === "selected") return book.status === "selected";
      if (coverStatusFilter === "published") {
        return book.status === "applied" || book.status === "already_applied";
      }
      return book.status === "error";
    })
    .sort((a, b) => {
      const missingA = a.cover_url ? 0 : 1;
      const missingB = b.cover_url ? 0 : 1;
      if (missingA !== missingB) return missingB - missingA;
      return (a.title || a.display_name).localeCompare(b.title || b.display_name, "fr");
    });

  const coverSection = (
      <section
        className="section"
        aria-labelledby="admin-covers-title"
        hidden={!onlyCovers && tab !== "covers"}
      >
        <div className="section-head">
          <h2 id="admin-covers-title">Validation des couvertures</h2>
        </div>
        <div className="form form-inline cover-filters">
          <label className="field">
            <span>Afficher</span>
            <select
              value={coverStatusFilter}
              onChange={(event) => setCoverStatusFilter(event.target.value)}
              aria-label="Filtrer les couvertures par statut"
            >
              <option value="all">Tous les livres</option>
              <option value="missing">Sans couverture</option>
              <option value="selected">Choix validé · à publier</option>
              <option value="published">Couverture publiée</option>
              <option value="error">En erreur</option>
            </select>
          </label>
          <span className="muted">
            {visibleCoverBooks.length} livre(s) affiché(s) · les livres sans
            couverture sont listés en premier.
          </span>
        </div>
        <p className="muted">
          Choisissez la couverture qui correspond à chaque livre, puis appliquez
          les choix validés par lot. Les aperçus sont chargés directement chez le
          fournisseur : ils ne transistent pas par AURA.
        </p>
        {coverMessage ? (
          <p role="status" className="alert alert-ok">
            {coverMessage}
          </p>
        ) : null}
        {coverCandidates.isError ? (
          <LoadError
            message="Candidats de couvertures indisponibles."
            error={coverCandidates.error}
            retrying={coverCandidates.isFetching}
            onRetry={() => void coverCandidates.refetch()}
          />
        ) : coverCandidates.isPending ? (
          <Loading label="Chargement des candidats de couvertures" />
        ) : (
          <>
            <div className="stat-grid">
              <div className="stat">
                <div className="value">{coverCandidates.data?.counts.books ?? 0}</div>
                <div className="label">Livres</div>
              </div>
              <div className="stat">
                <div className="value">
                  {coverCandidates.data?.counts.with_candidates ?? 0}
                </div>
                <div className="label">Livres avec candidats</div>
              </div>
              <div className="stat">
                <div className="value">
                  {coverCandidates.data?.counts.candidates ?? 0}
                </div>
                <div className="label">Candidats</div>
              </div>
              <div className="stat">
                <div className="value">{coverStats.missing}</div>
                <div className="label">Sans couverture</div>
              </div>
              <div className="stat">
                <div className="value">{coverStats.toPublish}</div>
                <div className="label">À publier</div>
              </div>
            </div>
            <p className="muted">
              {coverCoverage}% des livres suivis ont une couverture publiée ·
              généré le {formatTs(coverCandidates.data?.generated_at)}
            </p>
            {(coverCandidates.data?.books.length ?? 0) === 0 ? (
              <p className="empty">
                Aucun livre à valider pour le moment.
              </p>
            ) : (
              visibleCoverBooks.map((book) => {
                const candidates = book.candidates;
                const fallback =
                  book.chosen_url &&
                  candidates.some((candidate) => candidate.url === book.chosen_url)
                    ? book.chosen_url
                    : "";
                const selected = coverChoices[book.object_id] ?? fallback;
                const group = `cover-${book.object_id}`;
                const state = coverState(book);
                const published =
                  book.status === "applied" || book.status === "already_applied";
                return (
                  <article className="card" key={book.object_id}>
                    <div className="section-head">
                      <h3>{book.title || book.display_name}</h3>
                      <span className={state.className}>{state.label}</span>
                    </div>
                    <p className="muted">
                      {book.author || "Auteur inconnu"} ·{" "}
                      <span className="mono">{book.display_name}</span> ·{" "}
                      {OBJECT_STATUS_LABELS[book.status] ?? book.status}
                    </p>
                    <div className="form form-inline">
                      <label className="field">
                        <span>ISBN (optionnel)</span>
                        <input
                          type="text"
                          inputMode="numeric"
                          placeholder="978…"
                          aria-label={`ISBN pour ${book.title || book.display_name}`}
                          value={coverIsbns[book.object_id] ?? ""}
                          onChange={(event) =>
                            setCoverIsbns((current) => ({
                              ...current,
                              [book.object_id]: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <button
                        type="button"
                        className="btn"
                        disabled={!canWrite || searchCover.isPending}
                        onClick={() =>
                          searchCover.mutate({
                            object_id: book.object_id,
                            isbn: coverIsbns[book.object_id]?.trim() || null,
                            limit: 12,
                          })
                        }
                      >
                        Rechercher une couverture
                      </button>
                      {!canWrite ? (
                        <span className="muted">
                          La recherche exige le droit admin:write.
                        </span>
                      ) : null}
                    </div>
                    <CoverThumb
                      key={book.cover_url ?? "none"}
                      src={book.cover_url}
                      title={book.title || book.display_name}
                      alt={`Couverture actuelle de ${book.title || book.display_name}`}
                      label="Couverture publiée"
                    />
                    <div className="table-wrap">
                      <table className="table">
                        <thead>
                          <tr>
                            <th scope="col">Aperçu</th>
                            <th scope="col">Candidat</th>
                            <th scope="col">Correspondance</th>
                            <th scope="col">Choisir</th>
                          </tr>
                        </thead>
                        <tbody>
                          {candidates.length === 0 ? (
                            <tr>
                              <td className="muted" colSpan={4}>
                                Aucun candidat proposé pour ce livre.
                              </td>
                            </tr>
                          ) : (
                            candidates.map((candidate, index) => {
                              const badge = coverMatch(candidate.match);
                              const radioId = `${group}-${index}`;
                              return (
                                <tr key={`${candidate.provider}-${candidate.url}`}>
                                  <td>
                                    <CoverThumb
                                      src={candidate.url}
                                      title={book.title || book.display_name}
                                      alt={`Couverture proposée par ${candidate.provider} pour ${book.title || book.display_name}. Clic pour agrandir, double-clic pour valider.`}
                                      label="Clic : agrandir · Double-clic : valider"
                                      className="admin-cover-proposal"
                                      onClick={() => {
                                        setCoverChoices((current) => ({
                                          ...current,
                                          [book.object_id]: candidate.url,
                                        }));
                                        if (coverClickTimer.current !== null) {
                                          window.clearTimeout(coverClickTimer.current);
                                        }
                                        coverClickTimer.current = window.setTimeout(() => {
                                          openCoverZoom({
                                            url: candidate.url,
                                            title: book.title || book.display_name,
                                            author: book.author,
                                            provider: candidate.provider,
                                            objectId: book.object_id,
                                            status: book.status,
                                            fallbackUrl: book.cover_url,
                                          });
                                          coverClickTimer.current = null;
                                        }, 250);
                                      }}
                                      onDoubleClick={() => {
                                        if (coverClickTimer.current !== null) {
                                          window.clearTimeout(coverClickTimer.current);
                                          coverClickTimer.current = null;
                                        }
                                        quickSelectCover({
                                          url: candidate.url,
                                          title: book.title || book.display_name,
                                          objectId: book.object_id,
                                          status: book.status,
                                        });
                                      }}
                                    />
                                  </td>
                                  <td className="name">
                                    <label htmlFor={radioId}>
                                      {candidate.title || "Sans titre"}
                                    </label>
                                    <span className="muted table-sub">
                                      {candidate.author || "Auteur inconnu"}
                                    </span>
                                    <span className="muted table-sub">
                                      {candidate.provider}
                                    </span>
                                    {candidate.size ? (
                                      <span className="muted table-sub">
                                        Taille : {candidate.size}
                                      </span>
                                    ) : null}
                                  </td>
                                  <td>
                                    <span className={badge.className}>
                                      {badge.label}
                                    </span>
                                  </td>
                                  <td>
                                    <input
                                      id={radioId}
                                      type="radio"
                                      name={group}
                                      value={candidate.url}
                                      checked={selected === candidate.url}
                                      onChange={() =>
                                        setCoverChoices((current) => ({
                                          ...current,
                                          [book.object_id]: candidate.url,
                                        }))
                                      }
                                    />
                                  </td>
                                </tr>
                              );
                            })
                          )}
                          <tr>
                            <td className="name" colSpan={3}>
                              <label htmlFor={`${group}-none`}>Ne pas appliquer</label>
                              <span className="muted table-sub">
                                Aucune couverture ne sera importée pour ce livre.
                              </span>
                            </td>
                            <td>
                              <input
                                id={`${group}-none`}
                                type="radio"
                                name={group}
                                value=""
                                checked={selected === ""}
                                onChange={() =>
                                  setCoverChoices((current) => ({
                                    ...current,
                                    [book.object_id]: "",
                                  }))
                                }
                              />
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                    <div className="form form-inline">
                      <button
                        type="button"
                        className="btn"
                        disabled={
                          !canWrite || published || !candidates.some((candidate) => candidate.match === "exact")
                        }
                        onClick={() => {
                          const exact = candidates.find((candidate) => candidate.match === "exact");
                          if (exact) {
                            setCoverChoices((current) => ({
                              ...current,
                              [book.object_id]: exact.url,
                            }));
                            setCoverMessage(
                              `Correspondance exacte sélectionnée pour « ${book.title || book.display_name} ».`,
                            );
                          }
                        }}
                      >
                        Choisir la correspondance exacte
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary"
                        disabled={!canWrite || selectCover.isPending}
                        onClick={() =>
                          selectCover.mutate({
                            object_id: book.object_id,
                            candidate_url: selected || null,
                          })
                        }
                      >
                        Valider le choix
                      </button>
                      <ConfirmAction
                        label="Remplacer la couverture"
                        title={`Remplacer la couverture de ${book.title || book.display_name}`}
                        message={
                          <>
                            Le choix validé pour « {book.title || book.display_name} »
                            sera effacé.
                            {published
                              ? " ATTENTION : cette couverture a déjà été publiée ; l'effacement peut être refusé et ne retire pas la couverture déjà en ligne."
                              : " Sélectionnez ensuite une nouvelle couverture."}
                          </>
                        }
                        confirmLabel="Effacer le choix"
                        className="btn"
                        pending={clearCover.isPending}
                        disabled={!canWrite || !book.chosen_url || clearCover.isPending}
                        onConfirm={() => clearCover.mutate(book.object_id)}
                      />
                      {!canWrite ? (
                        <span className="muted">
                          La validation exige le droit admin:write.
                        </span>
                      ) : null}
                    </div>
                  </article>
                );
              })
            )}
            <div className="card">
              <h3>Application par lot</h3>
              <p className="muted">
                Applique les couvertures dont le choix a été validé. La simulation
                ne modifie rien et permet de vérifier le résultat.
              </p>
              <div className="form form-inline">
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={coverDryRun}
                    onChange={(event) => setCoverDryRun(event.target.checked)}
                  />
                  Simulation
                </label>
                <label className="field">
                  <span>Limite</span>
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={coverLimit}
                    onChange={(event) => setCoverLimit(Number(event.target.value))}
                  />
                </label>
                <ConfirmAction
                  label="Appliquer les couvertures validées"
                  title={
                    coverDryRun
                      ? "Simuler l'application des couvertures"
                      : "Appliquer les couvertures validées"
                  }
                  message={
                    coverDryRun
                      ? "Simuler l'application des couvertures validées ? Aucune couverture ne sera modifiée."
                      : `Appliquer les couvertures validées (jusqu'à ${coverLimit} livre(s)) ? Les couvertures sélectionnées seront remplacées, sans annulation possible.`
                  }
                  confirmLabel={coverDryRun ? "Simuler" : "Appliquer"}
                  danger={!coverDryRun}
                  className="btn btn-primary"
                  pending={applySelectedCovers.isPending}
                  disabled={
                    !canWrite ||
                    !Number.isInteger(coverLimit) ||
                    coverLimit < 1 ||
                    coverLimit > 200
                  }
                  onConfirm={() =>
                    applySelectedCovers.mutate({
                      dry_run: coverDryRun,
                      confirm: true,
                      limit: coverLimit,
                    })
                  }
                />
                {!canWrite ? (
                  <span className="muted">
                    L'application exige le droit admin:write.
                  </span>
                ) : null}
              </div>
              {coverApplyResult ? (
                <p role="status" className="alert alert-ok">
                  {coverApplyResult.dry_run ? "Simulation terminée" : "Application terminée"}{" "}
                  : {coverApplyResult.applied} appliquée(s),{" "}
                  {coverApplyResult.failed} échec(s),{" "}
                  {coverApplyResult.skipped} ignoré(s).
                </p>
              ) : null}
            </div>
          </>
        )}
      </section>
  );

  if (onlyCovers) {
    return (
      <div className="stack admin-page">
        <div className="page-head">
          <div className="page-title">
            <h1>Validation des couvertures</h1>
            <p className="muted page-sub">
              Candidats iTunes/Open Library par livre audio. La publication
              reste une action explicite et réversible par la revue.
            </p>
          </div>
        </div>
        {error ? (
          <p role="alert" className="alert alert-error">
            {error}
            <button type="button" className="btn btn-ghost btn-small" onClick={() => setError(null)}>
              Fermer
            </button>
          </p>
        ) : null}
        {coverSection}
      </div>
    );
  }

  return (
    <div className="stack admin-page">
      <div className="page-head">
        <div className="page-title">
          <h1>Administration</h1>
          <p className="muted page-sub">
            Applications, espaces, buckets et identités machine-à-machine.
            {canWrite
              ? " Votre rôle peut créer, modifier, activer/désactiver, faire tourner et révoquer."
              : " Lecture seule (les mutations exigent le rôle administrateur)."}
          </p>
        </div>
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

      <div hidden={tab !== "overview"}>
        <PortalStats enabled={canAdmin} />
      </div>

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
            onClick={() => {
              setOrphanCleanupResults({});
              queryClient.setQueryData(STORAGE_ORPHANS_QUERY_KEY, undefined);
              void storageOrphans.refetch();
            }}
          >
            {storageOrphans.isFetching ? "Analyse…" : "Analyser le stockage"}
          </button>
        </div>
        <p className="muted">
          Fichiers présents au stockage sans fiche au catalogue, octets laissés par des
          envois abandonnés et envois en plusieurs parties orphelins. La corbeille n'en
          fait pas partie. L'analyse est paginée par curseur ; les pages sont accumulées.
          Le nettoyage est une action distincte, confirmée et limitée à 100 fichiers et
          100 envois par appel et par bucket. Les éléments déjà tentés sont exclus du lot
          suivant jusqu'à réinitialisation explicite.
        </p>
        {storageOrphans.isError ? (
          <p role="alert" className="alert alert-error">
            Analyse du stockage indisponible.
          </p>
        ) : storageOrphans.data ? (
          <ul className="plain-list" data-testid="storage-orphans">
            {storageOrphans.data.buckets.map((entry) => {
              const batch = buildOrphanCleanupBatch(entry, orphanCleanupExclusions[entry.bucket]);
              const keyCount = batch.input.keys?.length ?? 0;
              const uploadCount = batch.input.uploads?.length ?? 0;
              const candidateCount = keyCount + uploadCount;
              const cleanupResult = orphanCleanupResults[entry.bucket];
              return (
                <li key={entry.bucket}>
                  <strong>{entry.bucket}</strong> :{" "}
                  {entry.error
                    ? "stockage indisponible"
                    : `${entry.orphans?.length ?? 0} fichier(s) non référencé(s) (${formatBytes(
                        entry.orphan_bytes ?? 0,
                      )}), ${entry.stale_uploads?.length ?? 0} envoi(s) en parties abandonné(s) sur ${
                        entry.scanned ?? 0
                      } objet(s) analysé(s)${entry.next_start_after ? " — analyse partielle" : ""}`}
                  {!entry.error && entry.next_start_after ? (
                    <div className="form form-inline">
                      <span className="muted">
                        Reprise après <code>{entry.next_start_after}</code>
                      </span>
                      <button
                        type="button"
                        className="btn btn-ghost btn-small"
                        aria-label={`Charger la suite du scan de ${entry.bucket}`}
                        disabled={storageOrphans.isFetching || loadMoreStorageOrphans.isPending}
                        onClick={() =>
                          loadMoreStorageOrphans.mutate({
                            bucket: entry.bucket,
                            startAfter: entry.next_start_after!,
                          })
                        }
                      >
                        {loadMoreStorageOrphans.isPending &&
                        loadMoreStorageOrphans.variables?.bucket === entry.bucket
                          ? "Chargement…"
                          : "Charger la suite du scan"}
                      </button>
                    </div>
                  ) : null}
                  {canWrite && (batch.excludedKeys > 0 || batch.excludedUploads > 0) ? (
                    <div className="form form-inline">
                      <span className="muted">
                        {batch.excludedKeys} fichier(s) et {batch.excludedUploads} envoi(s)
                        déjà tentés sont exclus pour ne pas bloquer la suite du traitement.
                      </span>
                      <button
                        type="button"
                        className="btn btn-ghost btn-small"
                        onClick={() =>
                          setOrphanCleanupExclusions((current) => {
                            const next = { ...current };
                            delete next[entry.bucket];
                            return next;
                          })
                        }
                      >
                        Réinitialiser les exclusions de {entry.bucket}
                      </button>
                    </div>
                  ) : null}
                  {canWrite && !entry.error && candidateCount > 0 ? (
                    <div className="form form-inline">
                      <ConfirmAction
                        label="Nettoyer les orphelins"
                        ariaLabel={`Nettoyer les orphelins de ${entry.bucket}`}
                        title={`Nettoyer les orphelins de ${entry.bucket}`}
                        message={
                          <>
                            Supprimer définitivement {keyCount} fichier(s) non référencé(s) et
                            abandonner {uploadCount} envoi(s) multipart du bucket {entry.bucket} ?
                            Chaque élément sera revérifié juste avant l'action ; les éléments
                            devenus légitimes ou trop récents seront ignorés.
                            <details>
                              <summary>Éléments concernés par ce lot</summary>
                              <ul>
                                {batch.input.keys?.map((key) => (
                                  <li key={key}><code>{key}</code></li>
                                ))}
                                {batch.input.uploads?.map((upload) => (
                                  <li key={upload.upload_id}>
                                    <code>{upload.key}</code> — envoi <code>{upload.upload_id}</code>
                                  </li>
                                ))}
                              </ul>
                            </details>
                          </>
                        }
                        confirmLabel="Nettoyer"
                        danger
                        pending={
                          cleanupStorageOrphans.isPending &&
                          cleanupStorageOrphans.variables?.bucket === entry.bucket
                        }
                        disabled={storageOrphans.isFetching || cleanupStorageOrphans.isPending}
                        onConfirm={() => cleanupStorageOrphans.mutate(batch.input)}
                      />
                      {batch.remainingKeys > 0 || batch.remainingUploads > 0 ? (
                        <span className="muted">
                          Lot limité : {batch.remainingKeys} fichier(s) et{" "}
                          {batch.remainingUploads} envoi(s) restant(s). Relancez le nettoyage
                          pour traiter la suite.
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                  {!canWrite && !entry.error && candidateCount > 0 ? (
                    <p className="muted">Le nettoyage exige le droit admin:write.</p>
                  ) : null}
                  {cleanupResult ? (
                    <div
                      role="status"
                      data-testid={`orphan-cleanup-result-${entry.bucket}`}
                      className={`alert ${cleanupResult.skipped.length > 0 ? "alert-warn" : "alert-ok"}`}
                    >
                      Nettoyage de {entry.bucket} : {cleanupResult.removed.length}{" "}
                      fichier(s) supprimé(s), {cleanupResult.aborted_uploads.length}{" "}
                      envoi(s) abandonné(s), {cleanupResult.skipped.length} ignoré(s).
                      {cleanupResult.removed.length > 0 ? (
                        <details>
                          <summary>Fichiers supprimés</summary>
                          <ul>
                            {cleanupResult.removed.map((key) => (
                              <li key={key}><code>{key}</code></li>
                            ))}
                          </ul>
                        </details>
                      ) : null}
                      {cleanupResult.aborted_uploads.length > 0 ? (
                        <details>
                          <summary>Envois multipart abandonnés</summary>
                          <ul>
                            {cleanupResult.aborted_uploads.map((uploadId) => (
                              <li key={uploadId}><code>{uploadId}</code></li>
                            ))}
                          </ul>
                        </details>
                      ) : null}
                      {cleanupResult.skipped.length > 0 ? (
                        <details>
                          <summary>Éléments ignorés et motifs</summary>
                          <ul>
                            {cleanupResult.skipped.map((item, index) => (
                              <li key={`${item.key}-${index}`}>
                                <code>{item.key}</code> : {orphanSkipReason(item.reason)}
                              </li>
                            ))}
                          </ul>
                        </details>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
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
          {canWrite ? (
            <ConfirmAction
              label="Lancer une vérification d'intégrité"
              title="Vérifier l'intégrité maintenant"
              message="Lancer une passe de vérification bornée ? Les fichiers dus seront relus et leur SHA-256 comparé au catalogue. Un défaut peut bloquer le fichier ; aucun octet ne sera supprimé ni réécrit."
              confirmLabel="Vérifier"
              pending={scrubIntegrity.isPending}
              onConfirm={() => scrubIntegrity.mutate()}
            />
          ) : null}
        </div>
        {scrubIntegrity.isSuccess ? (
          <p
            role="status"
            data-testid="scrub-result"
            className={`alert ${
              scrubIntegrity.data.mismatch > 0 ||
              scrubIntegrity.data.missing > 0 ||
              scrubIntegrity.data.error > 0
                ? "alert-warn"
                : "alert-ok"
            }`}
          >
            Vérification terminée : {scrubIntegrity.data.ok} intact(s),{" "}
            {scrubIntegrity.data.mismatch} altéré(s), {scrubIntegrity.data.missing} absent(s),{" "}
            {scrubIntegrity.data.error} erreur(s), {formatBytes(scrubIntegrity.data.bytes)} relu(s).
            {scrubIntegrity.data.mismatch > 0 || scrubIntegrity.data.missing > 0
              ? " Restaurez les fichiers en défaut depuis la sauvegarde, puis re-vérifiez-les."
              : ""}
            {scrubIntegrity.data.error > 0
              ? " Une erreur de stockage interrompt la passe : réessayez quand le stockage répond."
              : ""}
          </p>
        ) : null}
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
            {Object.values(reverifyResults).map((result) => (
              <p
                key={result.id}
                role="status"
                data-testid={`reverify-result-${result.id}`}
                className={`alert ${result.status === "available" ? "alert-ok" : "alert-warn"}`}
              >
                Re-vérification de <code>{result.id}</code> :{" "}
                {result.status === "available"
                  ? "contenu conforme, objet de nouveau disponible."
                  : "contenu toujours divergent, objet conservé en état suspect."}{" "}
                Taille relue : {formatBytes(result.size_bytes)}. SHA-256 calculé :{" "}
                <code>{result.checksum_sha256}</code>.
                {result.status === "suspect"
                  ? " Restaurez les octets attendus depuis la sauvegarde avant de réessayer."
                  : ""}
              </p>
            ))}
            {integrity.data.problems.length > 0 ? (
              <>
                <p role="alert" className="alert alert-error">
                  Des fichiers ne correspondent plus à leur empreinte vérifiée ou ont
                  disparu du stockage : restaurez-les depuis la sauvegarde.
                </p>
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Objet</th>
                      <th scope="col">Espace</th>
                      <th scope="col">Constat</th>
                      <th scope="col">Relu le</th>
                      {canWrite ? <th scope="col">Action</th> : null}
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
                        {canWrite ? (
                          <td>
                            <ConfirmAction
                              label="Re-vérifier"
                              ariaLabel={`Re-vérifier ${problem.display_name}`}
                              title={`Re-vérifier ${problem.display_name}`}
                              message={`Relire les octets de ${problem.display_name} (${problem.id}) et recalculer leur SHA-256 ? Si le contenu correspond au catalogue, l'objet redeviendra disponible ; sinon il restera suspect. Aucun octet ne sera supprimé.`}
                              confirmLabel="Re-vérifier"
                              pending={
                                reverifyObject.isPending && reverifyObject.variables === problem.id
                              }
                              disabled={reverifyObject.isPending}
                              onConfirm={() => reverifyObject.mutate(problem.id)}
                            />
                          </td>
                        ) : null}
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
        aria-labelledby="admin-maintenance-title"
        hidden={tab !== "overview"}
      >
        <div className="section-head">
          <h2 id="admin-maintenance-title">Maintenance et récupération</h2>
        </div>
        <p className="muted">
          Actions de maintenance du stockage, toutes réservées au droit{" "}
          <code>admin:write</code>. Chaque commande demande une confirmation explicite
          et affiche les compteurs retournés par l'API.
        </p>
        {!canWrite ? (
          <p className="muted">Ces commandes sont en lecture seule pour votre compte.</p>
        ) : (
          <>
            <article className="card">
              <h3>Nettoyage des objets terminés</h3>
              <p className="muted">
                Reprend le nettoyage des octets des objets failed, aborted, deleted ou
                expired vieux de plus de sept jours. Une fiche n'est supprimée qu'après
                suppression effective de ses octets.
              </p>
              <ConfirmAction
                label="Nettoyer les objets terminés"
                title="Nettoyer les objets terminés"
                message={`Supprimer définitivement les octets puis les fiches des objets terminés de plus de sept jours, dans tous les espaces (jusqu'à ${TERMINAL_RECONCILE_LIMIT} lignes inspectées par état) ? Les échecs de stockage conservent les fiches pour une nouvelle tentative.`}
                confirmLabel="Nettoyer"
                danger
                pending={reconcileTerminal.isPending}
                onConfirm={() => reconcileTerminal.mutate()}
              />
              {reconcileTerminal.isSuccess ? (
                <p
                  role="status"
                  data-testid="terminal-reconcile-result"
                  className={`alert ${reconcileTerminal.data.storage_failures > 0 ? "alert-warn" : "alert-ok"}`}
                >
                  Objets terminés : {reconcileTerminal.data.cleaned} fiche(s) nettoyée(s),{" "}
                  {reconcileTerminal.data.storage_deletes_attempted} suppression(s) stockage
                  tentée(s), {reconcileTerminal.data.storage_failures} échec(s) stockage.
                  {reconcileTerminal.data.storage_failures > 0
                    ? " Les fiches en échec sont conservées : réessayez plus tard."
                    : ""}
                </p>
              ) : null}
            </article>
            <article className="card">
              <h3>Réconciliation inverse</h3>
              <p className="muted">
                Compare le stockage au catalogue, dans chaque bucket enregistré (au plus
                500 clés inspectées par bucket). Les révisions sont exclues. Commencez par
                la simulation : seule la suppression explicite efface des octets.
              </p>
              <div className="form form-inline">
                <ConfirmAction
                  label="Analyser la réconciliation inverse"
                  title="Simuler la réconciliation inverse"
                  message="Lister les clés du stockage qu'aucune fiche du catalogue ne référence ? Cette simulation ne supprime aucun octet."
                  confirmLabel="Simuler"
                  pending={reconcileReverse.isPending && reconcileReverse.variables === true}
                  disabled={reconcileReverse.isPending}
                  onConfirm={() => reconcileReverse.mutate(true)}
                />
                <ConfirmAction
                  label="Supprimer les orphelins détectés"
                  title="Supprimer les orphelins du stockage"
                  message="Supprimer définitivement les clés non référencées trouvées dans tous les buckets enregistrés ? Jusqu'à 500 clés sont inspectées par bucket. Cette action est irréversible et ne demande pas une nouvelle simulation préalable."
                  confirmLabel="Supprimer"
                  danger
                  pending={reconcileReverse.isPending && reconcileReverse.variables === false}
                  disabled={reconcileReverse.isPending}
                  onConfirm={() => reconcileReverse.mutate(false)}
                />
              </div>
              {reconcileReverse.isSuccess ? (
                <div
                  role="status"
                  data-testid="reverse-reconcile-result"
                  className={`alert ${reconcileReverse.data.failures > 0 ? "alert-warn" : "alert-ok"}`}
                >
                  {reconcileReverse.data.dry_run ? "Simulation terminée" : "Suppression terminée"} :{" "}
                  {reconcileReverse.data.scanned} clé(s) analysée(s), {reconcileReverse.data.orphans}{" "}
                  orpheline(s), {reconcileReverse.data.deleted} supprimée(s),{" "}
                  {reconcileReverse.data.failures} échec(s).
                  {reconcileReverse.data.dry_run && reconcileReverse.data.orphans > 0
                    ? " Vérifiez les clés listées avant de lancer la suppression."
                    : ""}
                  {reconcileReverse.data.orphan_keys.length > 0 ? (
                    <details>
                      <summary>Clés orphelines retournées (50 maximum)</summary>
                      <ul>
                        {reconcileReverse.data.orphan_keys.map((orphan) => (
                          <li key={`${orphan.bucket}:${orphan.key}`}>
                            <code>{orphan.bucket}/{orphan.key}</code> —{" "}
                            {orphan.size === null ? "taille inconnue" : formatBytes(orphan.size)}
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </div>
              ) : null}
            </article>
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
                {activeSpaceItems.map((s) => (
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
                createIdentity.isPending || activeSpaceItems.length === 0 || idScopes.length === 0
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
                {activeSpaceItems.map((s) => (
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
                activeSpaceItems.length === 0 ||
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

      {coverSection}


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

      {coverZoom ? (
        <Dialog
          open
          title={`Aperçu — ${coverZoom.title}`}
          onClose={() => setCoverZoom(null)}
        >
          <div className="cover-zoom">
            <figure className="cover-zoom-item">
              <img
                src={coverZoom.url}
                alt={`Couverture agrandie de ${coverZoom.title}`}
                referrerPolicy="no-referrer"
              />
              <figcaption className="muted">
                Candidat · {coverZoom.provider}
              </figcaption>
            </figure>
            <figure className="cover-zoom-item">
              {coverZoom.fallbackUrl ? (
                <img
                  src={coverZoom.fallbackUrl}
                  alt={`Couverture actuelle de ${coverZoom.title}`}
                  referrerPolicy="no-referrer"
                />
              ) : (
                <span
                  className="admin-jacket"
                  role="img"
                  aria-label={`Jaquette AURA pour ${coverZoom.title}`}
                >
                  <span aria-hidden="true">
                    {(coverZoom.title || "Livre").trim().charAt(0).toUpperCase()}
                  </span>
                  <span className="admin-jacket-copy">
                    <span className="admin-jacket-kicker">Livre audio</span>
                    <span className="admin-jacket-title">{coverZoom.title}</span>
                    <span className="admin-jacket-author">{coverZoom.author || "AURA"}</span>
                  </span>
                </span>
              )}
              <figcaption className="muted">Couverture actuelle</figcaption>
            </figure>
          </div>
          <p className="muted">
            {coverZoom.author || "Auteur inconnu"} · source : {coverZoom.provider}
          </p>
          <p className="muted">
            Double-cliquez sur l’image dans la galerie pour valider directement
            ce choix.
          </p>
          <div className="dialog-actions">
            <button
              type="button"
              className="btn"
              onClick={() => setCoverZoom(null)}
            >
              Fermer
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!canWrite || selectCover.isPending}
              onClick={() => quickSelectCover(coverZoom)}
            >
              Choisir cette couverture
            </button>
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}
