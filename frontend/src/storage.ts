import { INITIAL_DATA, type WorkspaceData } from './model'

const STORAGE_KEY = 'geo-workbench-demo-v1'

function cloneInitialData(): WorkspaceData {
  return structuredClone(INITIAL_DATA)
}

export function loadWorkspace(): WorkspaceData {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return cloneInitialData()
    const value: unknown = JSON.parse(raw)
    if (!value || typeof value !== 'object' || !('schemaVersion' in value) || value.schemaVersion !== 1 || !('questions' in value) || !Array.isArray(value.questions) || !('samples' in value) || !Array.isArray(value.samples)) {
      return cloneInitialData()
    }
    return value as WorkspaceData
  } catch {
    return cloneInitialData()
  }
}

export function saveWorkspace(data: WorkspaceData): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
}

export function resetWorkspace(): WorkspaceData {
  localStorage.removeItem(STORAGE_KEY)
  return cloneInitialData()
}
