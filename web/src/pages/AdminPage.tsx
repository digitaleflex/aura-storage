import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, hasAdminAccess, hasScope, SERVICE_SCOPES } from "../lib/api";
import type {
  ApplicationItem,
  BucketListedItem,
  IdentityItem,
  SpaceItem,
} from "../lib/api";
import { useAuth, useSession } from "../lib/auth";
import { ConfirmAction, Dialog } from "../components/Dialog";
import { OneTimeToken } from "../components/OneTimeToken";

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

/** Active/disabled chip shared by applications and spaces. */
function lifecycleState(status: string): { label: string; className: string } {
  return status === "active"
    ? { label: "Actif", className: "chip chip-ok" }
    : { label: "Désactivé", className: "chip chip-muted" };
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

/** Administration console: registries plus `admin:write` mutations. */
export function AdminPage() {
  const { csrf } = useAuth();
  const session = useSession();
  const queryClient = useQueryClient();
  const canAdmin = hasAdminAccess(session.data?.role);
  const canWrite = hasScope(session.data?.scopes, "admin:write");

  const [error, setError] = useState<string | null>(null);
  const [oneTimeToken, setOneTimeToken] = useState<string | null>(null);
  const [editingApp, setEditingApp] = useState<ApplicationItem | null>(null);
  const [editingSpace, setEditingSpace] = useState<SpaceItem | null>(null);

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
  // Register-bucket form
  const [bucketSpace, setBucketSpace] = useState("");
  const [bucketName, setBucketName] = useState("");

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
  const buckets = useQuery({
    queryKey: ["admin", "buckets"],
    queryFn: () => api.listBuckets(),
    enabled: canAdmin,
    retry: false,
  });

  function refreshAdmin() {
    void queryClient.invalidateQueries({ queryKey: ["admin"] });
  }

  function fail(err: unknown, fallback: string) {
    setError(err instanceof Error ? err.message : fallback);
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
    <div className="stack">
      <h1>Administration</h1>
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

      <section className="section" aria-labelledby="admin-stats-title">
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
            tentée(s).
          </p>
        ) : null}
        {stats.isError ? (
          <p role="alert" className="alert alert-error">
            Statistiques indisponibles.
          </p>
        ) : stats.isPending ? (
          <p className="muted">Chargement…</p>
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
                    {status} : {count}
                  </span>
                ))}
              </p>
            ) : null}
          </>
        )}
      </section>

      <section className="section" aria-labelledby="admin-apps-title">
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
          <p role="alert" className="alert alert-error">
            Applications indisponibles.
          </p>
        ) : applications.isPending ? (
          <p className="muted">Chargement…</p>
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

      <section className="section" aria-labelledby="admin-spaces-title">
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
          <p role="alert" className="alert alert-error">
            Espaces indisponibles.
          </p>
        ) : spaces.isPending ? (
          <p className="muted">Chargement…</p>
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

      <section className="section" aria-labelledby="admin-buckets-title">
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
          <p role="alert" className="alert alert-error">
            Buckets indisponibles.
          </p>
        ) : buckets.isPending ? (
          <p className="muted">Chargement…</p>
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

      <section className="section" aria-labelledby="admin-identities-title">
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
          <p role="alert" className="alert alert-error">
            Identités indisponibles.
          </p>
        ) : identities.isPending ? (
          <p className="muted">Chargement…</p>
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

      {editingApp ? (
        <EditApplicationDialog
          application={editingApp}
          pending={updateApp.isPending}
          onClose={() => setEditingApp(null)}
          onSubmit={(name) => updateApp.mutate({ id: editingApp.id, name })}
        />
      ) : null}

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
