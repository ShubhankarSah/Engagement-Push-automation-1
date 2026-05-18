// Google Apps Script — paste this into your Apps Script editor and redeploy as a Web App

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();

    // ── Column index map (1-based) ──────────────────────────────────────────
    // A=1  id
    // B=2  title          ← overwritten
    // C=3  image_link     ← overwritten
    // D=4  TE1            ← overwritten
    // E=5  MS1            ← overwritten
    // F=6  CTA1           ← left as-is
    // G=7  link           ← left as-is

    var action = data.action || "append"; // default to append for backward-compat

    if (action === "update") {
      // ── UPDATE MODE: find the row by id and patch only B, C, D, E ────────
      var targetId = data.id;         // e.g. "PUSH 1"
      var lastRow  = sheet.getLastRow();
      var found    = false;

      for (var i = 2; i <= lastRow; i++) {   // row 1 is the header
        var cellId = sheet.getRange(i, 1).getValue().toString().trim();

        if (cellId === targetId) {
          // Overwrite only the four dynamic columns
          sheet.getRange(i, 2).setValue(data.title       || "");  // B: title
          sheet.getRange(i, 3).setValue(data.image_link  || "");  // C: image_link
          sheet.getRange(i, 4).setValue(data.TE1         || "");  // D: TE1
          sheet.getRange(i, 5).setValue(data.MS1         || "");  // E: MS1
          // Columns F (CTA1) and G (link) are intentionally untouched
          found = true;
          break;
        }
      }

      if (!found) {
        // Row with that id doesn't exist yet — append a new one
        sheet.appendRow([
          data.id         || "",
          data.title      || "",
          data.image_link || "",
          data.TE1        || "",
          data.MS1        || "",
          "",  // CTA1 left blank for new rows
          ""   // link left blank for new rows
        ]);
      }

    } else {
      // ── APPEND MODE (legacy fallback) ────────────────────────────────────
      sheet.appendRow([
        data.id         || "",
        data.title      || "",
        data.image_link || "",
        data.TE1        || "",
        data.MS1        || "",
        data.CTA1       || "",
        data.link       || ""
      ]);
    }

    return ContentService
      .createTextOutput(JSON.stringify({ status: "Success" }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: "Error", error: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
