/* Export/import for RTI Sahayak's two localStorage-only datasets (Track's
 * filings, Save Draft's drafts) as one combined JSON backup file. Pure
 * client-side - no server involvement, no new API route. Shared by /track
 * and /draft via web/templates/partials/backup_controls.html, which owns
 * the UI; this file owns the data logic only.
 *
 * One combined export, not two separate ones: a user thinking "back up my
 * data" isn't thinking in terms of which page it came from, and it means a
 * single import on a fresh device restores everything in one step.
 */
(function () {
  var STORAGE_KEYS = { filings: 'rtiSahayakTrackFilings', drafts: 'rtiSahayakSavedDrafts' };
  var SCHEMA_VERSION = 1;
  // localStorage itself is capped around 5-10MB per origin in most browsers,
  // so a real export of this app's own data can never approach this - it's
  // a defensive ceiling against being handed an unrelated huge file, not a
  // tuned limit.
  var MAX_IMPORT_FILE_BYTES = 10 * 1024 * 1024;

  function safeParseArray(raw) {
    try {
      var parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function loadFilings() {
    return safeParseArray(localStorage.getItem(STORAGE_KEYS.filings));
  }

  function loadDrafts() {
    return safeParseArray(localStorage.getItem(STORAGE_KEYS.drafts));
  }

  function hasAnyData() {
    return loadFilings().length > 0 || loadDrafts().length > 0;
  }

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function exportBackup() {
    var filings = loadFilings();
    var drafts = loadDrafts();
    var backup = {
      app: "rti-sahayak",
      schema_version: SCHEMA_VERSION,
      exported_at: new Date().toISOString(),
      filings: filings,
      drafts: drafts,
    };
    var json = JSON.stringify(backup, null, 2);
    var blob = new Blob([json], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var now = new Date();
    var filename =
      "rti-sahayak-backup-" + now.getFullYear() + "-" + pad2(now.getMonth() + 1) + "-" + pad2(now.getDate()) + ".json";
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    return { filings_count: filings.length, drafts_count: drafts.length };
  }

  // Validates before touching anything - resolves with a normalized backup
  // object, or rejects with a plain-language Error the UI can show as-is.
  function readBackupFile(file) {
    return new Promise(function (resolve, reject) {
      if (!file) {
        reject(new Error("No file selected."));
        return;
      }
      if (file.size > MAX_IMPORT_FILE_BYTES) {
        reject(new Error("This file is too large to be a real RTI Sahayak backup (over 10 MB). Choose a different file."));
        return;
      }
      var reader = new FileReader();
      reader.onerror = function () {
        reject(new Error("Could not read this file."));
      };
      reader.onload = function () {
        var parsed;
        try {
          parsed = JSON.parse(String(reader.result));
        } catch (e) {
          reject(new Error("This file is not valid JSON."));
          return;
        }
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          reject(new Error("This file is valid JSON, but not an RTI Sahayak backup."));
          return;
        }
        if (parsed.app !== "rti-sahayak" || typeof parsed.schema_version === "undefined") {
          reject(new Error("This file is valid JSON, but not an RTI Sahayak backup."));
          return;
        }
        if (parsed.schema_version !== SCHEMA_VERSION) {
          var newer = parsed.schema_version > SCHEMA_VERSION;
          reject(
            new Error(
              "This backup was made with a " + (newer ? "newer" : "older") + " version of RTI Sahayak (schema v" +
                parsed.schema_version + ", this app reads v" + SCHEMA_VERSION + ") and can't be safely imported."
            )
          );
          return;
        }
        resolve({
          schema_version: parsed.schema_version,
          exported_at: parsed.exported_at || null,
          filings: Array.isArray(parsed.filings) ? parsed.filings : [],
          drafts: Array.isArray(parsed.drafts) ? parsed.drafts : [],
        });
      };
      reader.readAsText(file);
    });
  }

  // mode: 'merge' dedupes by id against what's already stored, keeping
  // existing data; 'replace' discards all current filings AND drafts first,
  // even if the backup itself is missing one category - "replace" means
  // this device's data becomes exactly the backup, not a partial swap.
  function importBackup(backup, mode) {
    var existingFilings = mode === "replace" ? [] : loadFilings();
    var existingDrafts = mode === "replace" ? [] : loadDrafts();

    var existingFilingIds = {};
    existingFilings.forEach(function (f) {
      if (f && f.id) existingFilingIds[f.id] = true;
    });
    var existingDraftIds = {};
    existingDrafts.forEach(function (d) {
      if (d && d.id) existingDraftIds[d.id] = true;
    });

    var filingsImported = 0;
    var filingsSkipped = 0;
    backup.filings.forEach(function (f) {
      if (!f || !f.id || existingFilingIds[f.id]) {
        filingsSkipped++;
        return;
      }
      existingFilings.push(f);
      existingFilingIds[f.id] = true;
      filingsImported++;
    });

    var draftsImported = 0;
    var draftsSkipped = 0;
    backup.drafts.forEach(function (d) {
      if (!d || !d.id || existingDraftIds[d.id]) {
        draftsSkipped++;
        return;
      }
      existingDrafts.push(d);
      existingDraftIds[d.id] = true;
      draftsImported++;
    });

    try {
      localStorage.setItem(STORAGE_KEYS.filings, JSON.stringify(existingFilings));
      localStorage.setItem(STORAGE_KEYS.drafts, JSON.stringify(existingDrafts));
    } catch (e) {
      throw new Error("Could not save the imported data to this browser's storage - it may be full or blocked.");
    }

    var summary = {
      mode: mode,
      filings_imported: filingsImported,
      filings_skipped: filingsSkipped,
      drafts_imported: draftsImported,
      drafts_skipped: draftsSkipped,
    };
    window.dispatchEvent(new CustomEvent("rtisahayak:backup-imported", { detail: summary }));
    return summary;
  }

  window.RTISahayakBackup = {
    SCHEMA_VERSION: SCHEMA_VERSION,
    hasAnyData: hasAnyData,
    exportBackup: exportBackup,
    readBackupFile: readBackupFile,
    importBackup: importBackup,
  };
})();
