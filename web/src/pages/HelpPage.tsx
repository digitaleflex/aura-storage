import { useNavigate } from "@tanstack/react-router";
import { useAuth } from "../lib/auth";
import { VaultMark } from "../components/VaultMark";

export function HelpPage() {
  const { logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="help-page" data-testid="help-page">
      <VaultMark />
      <div className="help-shell">
        <div className="help-header">
          <h1>Aide — AURA Vault</h1>
          <p className="help-subtitle">
            Guide rapide et réponses aux questions courantes
          </p>
        </div>

        <section className="help-card">
          <h2>Importer des fichiers</h2>
          <ul>
            <li>
              Allez sur la page <strong>Fichiers</strong> et cliquez sur{" "}
              <strong>Importer</strong>, ou glissez-déposez vos fichiers.
            </li>
            <li>
              Suivez la progression sur la page{" "}
              <strong>Transferts</strong> (pause, reprise, annulation par
              fichier).
            </li>
            <li>
              Les octets sont envoyés directement à SeaweedFS (S3) via des URLs
              présignées : l'API ne proxie jamais vos données.
            </li>
          </ul>
        </section>

        <section className="help-card">
          <h2>Partager des fichiers</h2>
          <ul>
            <li>
              Sélectionnez un fichier ou un dossier, puis cliquez sur{" "}
              <strong>Partager / Gérer</strong>.
            </li>
            <li>
              Choisissez une durée d'expiration et un nombre d'utilisations
              maximal.
            </li>
            <li>
              Copiez le lien généré et envoyez-le à vos destinataires. Aucun
              compte AURA n'est requis pour les destinataires.
            </li>
            <li>
              Vous pouvez révoquer un lien à tout moment depuis la page{" "}
              <strong>Partages</strong>.
            </li>
          </ul>
        </section>

        <section className="help-card">
          <h2>Corbeille</h2>
          <ul>
            <li>
              Supprimer un fichier le place dans la <strong>Corbeille</strong>{" "}
              (soft delete). Il reste récupérable.
            </li>
            <li>
              Cliquez sur <strong>Restaurer</strong> pour le remettre en place,
              ou sur <strong>Purger</strong> pour le supprimer définitivement.
            </li>
          </ul>
        </section>

        <section className="help-card">
          <h2>Sécurité</h2>
          <ul>
            <li>
              Vos fichiers sont chiffrés au repos (SSE-S3 AES-256 sur
              SeaweedFS).
            </li>
            <li>
              Chaque objet a une empreinte SHA-256 vérifiée à l'import.
            </li>
            <li>
              Toutes les actions sont journalisées (audit log immuable).
            </li>
          </ul>
        </section>

        <div className="help-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate({ to: "/" })}
          >
            Aller aux fichiers
          </button>
          <button
            type="button"
            className="btn btn-small btn-ghost"
            onClick={() => {
              void logout();
              navigate({ to: "/login" });
            }}
          >
            D&eacute;connexion
          </button>
        </div>
      </div>
    </div>
  );
}
