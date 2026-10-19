import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";

type FolderContextValue = {
  currentFolderId: string | null;
  setCurrentFolderId: (id: string | null) => void;
};

const FolderContext = createContext<FolderContextValue>({
  currentFolderId: null,
  setCurrentFolderId: () => {},
});

/**
 * Holds the folder the explorer is browsing. Mounted once above the router
 * outlet so the shell sidebar (`Layout`) and the explorer (`ObjectsPage`) share
 * one selection: clicking a folder in the sidebar filters the object list.
 */
export function FolderProvider({ children }: { children: ReactNode }) {
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  return (
    <FolderContext.Provider value={{ currentFolderId, setCurrentFolderId }}>
      {children}
    </FolderContext.Provider>
  );
}

export function useFolderNavigation() {
  return useContext(FolderContext);
}

export default FolderContext;
