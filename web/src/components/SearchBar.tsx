/**
 * Barre de recherche globale pour AURA Vault.
 *
 * Permet de rechercher des fichiers et dossiers depuis n'importe quelle page.
 * La recherche est débouncée (300 ms) pour éviter une requête par frappe.
 * Le raccourci clavier `/` met le focus sur le champ depuis n'importe où.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate } from "@tanstack/react-router";
import { api } from "../lib/api";
import { describeError } from "../lib/errors";

interface SearchResult {
  id: string;
  name: string;
  type: "file" | "folder";
  content_type?: string;
  size_bytes?: number;
  created_at?: number;
}

interface SearchBarProps {
  /** Callback appelé quand un résultat est sélectionné (naviguer vers l'élément) */
  onSelect?: (result: SearchResult) => void;
  /** Nombre max de résultats à afficher dans la liste déroulante */
  maxResults?: number;
  /** Placeholder du champ */
  placeholder?: string;
}

/**
 * Hook qui gère la recherche globale avec débounce.
 */
export function useGlobalSearch({
  onSelect,
  maxResults = 8,
}: SearchBarProps = {}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const navigate = useNavigate();

  const search = useCallback(
    async (value: string) => {
      const trimmed = value.trim();
      if (!trimmed) {
        setResults([]);
        setError(null);
        return;
      }

      setIsSearching(true);
      setError(null);

      try {
        // Recherche dans les objets (nom + contenu)
        const objectResp = await api.listObjects({
          q: trimmed,
          limit: Math.max(maxResults, 20),
          offset: 0,
        });

        const fileResults: SearchResult[] = objectResp.items.map((item) => ({
          id: item.id,
          name: item.display_name,
          type: "file",
          content_type: item.content_type,
          size_bytes: item.size_bytes,
          created_at: item.created_at,
        }));

        // Recherche dans les dossiers (nom)
        const folderResp = await api.listAllFolders();
        const folderResults: SearchResult[] = folderResp.items
          .filter((folder) =>
            folder.name.toLowerCase().includes(trimmed.toLowerCase())
          )
          .map((folder) => ({
            id: folder.id,
            name: folder.name,
            type: "folder",
          }));

        // Mélanger et limiter
        const allResults = [...fileResults, ...folderResults].slice(
          0,
          maxResults
        );
        setResults(allResults);
      } catch (err) {
        setError(describeError(err, "Recherche impossible."));
      } finally {
        setIsSearching(false);
      }
    },
    [maxResults],
  );

  const handleChange = (value: string) => {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(value), 300);
  };

  const selectResult = (result: SearchResult) => {
    setQuery("");
    setResults([]);
    if (onSelect) {
      onSelect(result);
    } else {
      // Navigation vers la page Fichiers avec le nom de l'élément comme filtre
      navigate({ to: "/", search: { q: result.name } });
    }
  };

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  return {
    query,
    setQuery,
    setResults,
    handleChange,
    results,
    isSearching,
    error,
    selectResult,
    isEmpty: results.length === 0 && query.trim().length > 0,
  };
}

export interface SearchBarPropsFull extends SearchBarProps {
  /** Si true, affiche le champ toujours ouvert (pas de bouton d'ouverture) */
  alwaysOpen?: boolean;
}

/**
 * Composant SearchBar : champ de recherche avec liste déroulante des résultats.
 */
export function SearchBar({
  onSelect,
  maxResults = 8,
  placeholder = "Rechercher fichiers et dossiers…",
  alwaysOpen = false,
}: SearchBarPropsFull) {
  const [isOpen, setIsOpen] = useState(alwaysOpen);
  const {
    query,
    setQuery,
    setResults,
    handleChange,
    results,
    isSearching,
    error,
    selectResult,
    isEmpty,
  } = useGlobalSearch({ onSelect, maxResults });

  const inputRef = useRef<HTMLInputElement | null>(null);

  // Raccourci clavier : `/` pour ouvrir/focus la recherche
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      // Ne pas intercepter si l'utilisateur est déjà en train de taper dans un input
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement
      ) {
        return;
      }

      if (
        event.key === "/" ||
        (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey))
      ) {
        event.preventDefault();
        setIsOpen(true);
        requestAnimationFrame(() => inputRef.current?.focus());
      }

      if (event.key === "Escape" && isOpen) {
        event.preventDefault();
        setIsOpen(false);
      }
    };

    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [isOpen]);

  const toggle = () => setIsOpen((prev) => !prev);

  if (!isOpen && !alwaysOpen) {
    return (
      <button
        type="button"
        className="search-toggle"
        onClick={toggle}
        title="Rechercher (raccourci : /)"
        aria-label="Ouvrir la recherche"
      >
        🔍
      </button>
    );
  }

  return (
    <div className="search-bar-container" data-testid="search-bar">
      <form
        className="search-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (results.length === 1 && results[0]) {
            selectResult(results[0]);
          }
        }}
      >
        <div className="search-input-wrapper">
          <span className="search-icon" aria-hidden="true">🔍</span>
          <input
            ref={inputRef}
            type="search"
            className="search-input"
            placeholder={placeholder}
            value={query}
            onChange={(e) => handleChange(e.target.value)}
            onFocus={() => setIsOpen(true)}
            autoComplete="off"
            spellCheck={false}
            aria-label="Recherche globale"
          />
          {query.trim().length > 0 && (
            <button
              type="button"
              className="search-clear"
              onClick={(e) => {
                e.preventDefault();
                setQuery("");
                setResults([]);
                inputRef.current?.focus();
              }}
              title="Effacer"
              aria-label="Effacer la recherche"
            >
              ✕
            </button>
          )}
        </div>

        {isSearching && (
          <div className="search-loading">
            <span className="search-loading-text">Recherche en cours…</span>
          </div>
        )}

        {error && (
          <div className="search-error" role="alert">
            {error}
          </div>
        )}

        {query.trim().length > 0 && !isSearching && (
          <div className="search-results" role="listbox">
            {isEmpty ? (
              <div className="search-result-empty" role="option">
                Aucun résultat pour « {query} »
              </div>
            ) : (
              results.map((result) => {
                if (!result) return null;
                return (
                  <button
                    key={result.id}
                    type="button"
                    className="search-result-item"
                    onClick={() => selectResult(result)}
                    role="option"
                  >
                    <span className="search-result-icon" aria-hidden="true">
                      {result.type === "folder" ? "📁" : "📄"}
                    </span>
                    <div className="search-result-info">
                      <span className="search-result-name">{result.name}</span>
                      <span className="search-result-meta">
                        {result.type === "folder"
                          ? "Dossier"
                          : `${result.content_type ?? "Fichier"} · ${
                              result.size_bytes != null
                                ? formatBytes(result.size_bytes)
                                : ""
                            }`}
                      </span>
                    </div>
                    <span className="search-result-action">
                      {result.type === "folder" ? "Ouvrir" : "Télécharger"}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        )}
      </form>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 o";
  const k = 1024;
  const sizes = ["o", "Ko", "Mo", "Go", "To"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}
