function openStore(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("tradeguard-files", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("files");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error("Local file storage is unavailable. Enable browser storage and try again."));
  });
}
export async function fileOperation(action: "put" | "get" | "delete", id: string, file?: File): Promise<File | undefined> {
  const db = await openStore();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction("files", action === "get" ? "readonly" : "readwrite");
    const store = transaction.objectStore("files");
    const request = action === "put" ? store.put(file, id) : action === "get" ? store.get(id) : store.delete(id);
    transaction.oncomplete = () => { db.close(); resolve(request.result as File | undefined); };
    transaction.onerror = () => { db.close(); reject(new Error("Unable to save or read the local document.")); };
  });
}
