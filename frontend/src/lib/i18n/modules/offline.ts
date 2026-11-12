import { defineCatalog } from "../catalog";

/** Offline mode: the status pill, banner, sync panel, offline register and sign-out guard. */
export const offlineMessages = defineCatalog({
  en: {
    status: {
      offline: "Offline",
      syncing: "Syncing…",
      pendingOne: "{count} waiting to sync",
      pendingMany: "{count} waiting to sync",
      failedOne: "{count} couldn't sync",
      failedMany: "{count} couldn't sync",
      openPanel: "Offline attendance",
    },
    banner: {
      title: "You're offline",
      body: "Showing what's saved on this device. Attendance you take is kept here and sent when you're back online. Other changes need a connection.",
      retry: "Check again",
      checking: "Checking…",
    },
    panel: {
      title: "Attendance taken offline",
      description:
        "Registers saved on this device. They are sent to the server automatically when the connection is back.",
      empty: "Nothing is waiting to sync.",
      sectionDate: "{section} · {date}",
      changesOne: "{count} change",
      changesMany: "{count} changes",
      willSubmit: "Will be submitted",
      draftOnly: "Saved as a draft",
      pending: "Waiting to sync",
      failed: "Couldn't sync",
      syncNow: "Sync now",
      syncing: "Syncing…",
      retry: "Try again",
      discard: "Discard",
      offlineHint: "You're offline. These will be sent when the connection is back.",
      discardTitle: "Discard the offline attendance for {section}?",
      discardBody:
        "The marks saved on this device are deleted. Nothing on the server changes.",
    },
    toast: {
      syncedOne: "{count} register synced",
      syncedMany: "{count} registers synced",
      syncedBody: "Attendance taken offline is now on the server.",
      failedOne: "{count} register couldn't sync",
      failedMany: "{count} registers couldn't sync",
      failedBody: "Open “Offline attendance” in the header to see why.",
      savedOffline: "Saved on this device",
      savedOfflineBody: "It will be sent when you're back online.",
      noConnectionSaved: "No connection — saved on this device",
    },
    errors: {
      alreadySubmitted:
        "This register was submitted on the server before your offline marks arrived, so they were not applied. Open it to compare, then discard these marks.",
      signInAgain: "Your session has ended. Sign in again to send this attendance.",
    },
    board: {
      savedOnDevice: "Saved on device",
      syncFailed: "Sync failed",
      staleBoard:
        "Offline: showing the sections saved on {date}. Their status updates when you're back online.",
      unknown: "Unknown offline",
      noBoard:
        "Today's registers aren't saved on this device. Open Attendance once while online to use it offline.",
    },
    register: {
      title: "Take attendance — offline",
      description: "{section} · {date}. Saved on this device and sent when you're back online.",
      summary: "{present} present · {absent} absent",
      saveDraft: "Save on this device",
      saveAndSubmit: "Submit when online",
      close: "Close",
      submittedReadOnly:
        "This register is already submitted. Changing it needs a connection.",
      notAvailable:
        "This section's student list isn't saved on this device. Open Attendance once while online to make it available offline.",
      fromSavedRegister: "Starting from the register as it was last seen online.",
      fromRoster: "Everyone starts as present. Tap the students who are not.",
    },
    signOut: {
      pendingTitle: "Sign out with attendance not yet sent?",
      pendingBodyOne:
        "{count} register taken offline hasn't reached the server yet. Signing out deletes it from this device.",
      pendingBodyMany:
        "{count} registers taken offline haven't reached the server yet. Signing out deletes them from this device.",
      signOutAnyway: "Sign out anyway",
      needsConnection: "Signing out needs a connection",
      needsConnectionBody: "You're offline. Sign out when you're back online.",
    },
  },
  ur: {
    status: {
      offline: "آف لائن",
      syncing: "بھیجا جا رہا ہے…",
      pendingOne: "{count} بھیجنا باقی",
      pendingMany: "{count} بھیجنا باقی",
      failedOne: "{count} نہیں بھیجا جا سکا",
      failedMany: "{count} نہیں بھیجے جا سکے",
      openPanel: "آف لائن حاضری",
    },
    banner: {
      title: "آپ آف لائن ہیں",
      body: "اس ڈیوائس پر محفوظ معلومات دکھائی جا رہی ہیں۔ جو حاضری آپ لگائیں گے وہ یہیں محفوظ رہے گی اور کنکشن بحال ہوتے ہی بھیج دی جائے گی۔ باقی تبدیلیوں کے لیے کنکشن ضروری ہے۔",
      retry: "دوبارہ چیک کریں",
      checking: "چیک ہو رہا ہے…",
    },
    panel: {
      title: "آف لائن لگائی گئی حاضری",
      description:
        "اس ڈیوائس پر محفوظ رجسٹر۔ کنکشن بحال ہوتے ہی یہ خود بخود سرور پر بھیج دیے جاتے ہیں۔",
      empty: "بھیجنے کے لیے کچھ باقی نہیں۔",
      sectionDate: "{section} · {date}",
      changesOne: "{count} تبدیلی",
      changesMany: "{count} تبدیلیاں",
      willSubmit: "جمع کر دیا جائے گا",
      draftOnly: "مسودے کے طور پر محفوظ",
      pending: "بھیجنا باقی",
      failed: "نہیں بھیجا جا سکا",
      syncNow: "ابھی بھیجیں",
      syncing: "بھیجا جا رہا ہے…",
      retry: "دوبارہ کوشش کریں",
      discard: "ختم کریں",
      offlineHint: "آپ آف لائن ہیں۔ کنکشن بحال ہوتے ہی یہ بھیج دیے جائیں گے۔",
      discardTitle: "{section} کی آف لائن حاضری ختم کریں؟",
      discardBody: "اس ڈیوائس پر محفوظ حاضری حذف ہو جائے گی۔ سرور پر کچھ نہیں بدلے گا۔",
    },
    toast: {
      syncedOne: "{count} رجسٹر بھیج دیا گیا",
      syncedMany: "{count} رجسٹر بھیج دیے گئے",
      syncedBody: "آف لائن لگائی گئی حاضری اب سرور پر ہے۔",
      failedOne: "{count} رجسٹر نہیں بھیجا جا سکا",
      failedMany: "{count} رجسٹر نہیں بھیجے جا سکے",
      failedBody: "وجہ دیکھنے کے لیے اوپر ”آف لائن حاضری“ کھولیں۔",
      savedOffline: "اس ڈیوائس پر محفوظ ہو گیا",
      savedOfflineBody: "کنکشن بحال ہوتے ہی بھیج دیا جائے گا۔",
      noConnectionSaved: "کنکشن نہیں — اس ڈیوائس پر محفوظ کر لیا گیا",
    },
    errors: {
      alreadySubmitted:
        "آپ کی آف لائن حاضری پہنچنے سے پہلے یہ رجسٹر سرور پر جمع ہو چکا تھا، اس لیے یہ تبدیلیاں لاگو نہیں ہوئیں۔ رجسٹر کھول کر موازنہ کریں، پھر انہیں ختم کر دیں۔",
      signInAgain: "آپ کا سیشن ختم ہو گیا ہے۔ یہ حاضری بھیجنے کے لیے دوبارہ سائن ان کریں۔",
    },
    board: {
      savedOnDevice: "ڈیوائس پر محفوظ",
      syncFailed: "بھیجا نہیں جا سکا",
      staleBoard:
        "آف لائن: {date} کو محفوظ کیے گئے سیکشن دکھائے جا رہے ہیں۔ ان کی حیثیت کنکشن بحال ہونے پر اپ ڈیٹ ہوگی۔",
      unknown: "آف لائن نامعلوم",
      noBoard:
        "آج کے رجسٹر اس ڈیوائس پر محفوظ نہیں۔ آف لائن استعمال کے لیے ایک بار آن لائن ہوتے ہوئے حاضری کا صفحہ کھولیں۔",
    },
    register: {
      title: "حاضری لگائیں — آف لائن",
      description: "{section} · {date}۔ اس ڈیوائس پر محفوظ ہوگی اور کنکشن بحال ہوتے ہی بھیج دی جائے گی۔",
      summary: "{present} حاضر · {absent} غیر حاضر",
      saveDraft: "اس ڈیوائس پر محفوظ کریں",
      saveAndSubmit: "آن لائن ہوتے ہی جمع کریں",
      close: "بند کریں",
      submittedReadOnly: "یہ رجسٹر جمع ہو چکا ہے۔ اس میں تبدیلی کے لیے کنکشن ضروری ہے۔",
      notAvailable:
        "اس سیکشن کی طلبہ کی فہرست اس ڈیوائس پر محفوظ نہیں۔ آف لائن استعمال کے لیے ایک بار آن لائن ہوتے ہوئے حاضری کا صفحہ کھولیں۔",
      fromSavedRegister: "رجسٹر وہیں سے شروع ہو رہا ہے جیسا آخری بار آن لائن دیکھا گیا تھا۔",
      fromRoster: "سب کو حاضر سے شروع کیا گیا ہے۔ جو حاضر نہیں ان پر ٹیپ کریں۔",
    },
    signOut: {
      pendingTitle: "بھیجی نہ گئی حاضری کے ساتھ سائن آؤٹ کریں؟",
      pendingBodyOne:
        "آف لائن لگایا گیا {count} رجسٹر ابھی سرور تک نہیں پہنچا۔ سائن آؤٹ کرنے سے یہ اس ڈیوائس سے حذف ہو جائے گا۔",
      pendingBodyMany:
        "آف لائن لگائے گئے {count} رجسٹر ابھی سرور تک نہیں پہنچے۔ سائن آؤٹ کرنے سے یہ اس ڈیوائس سے حذف ہو جائیں گے۔",
      signOutAnyway: "پھر بھی سائن آؤٹ کریں",
      needsConnection: "سائن آؤٹ کے لیے کنکشن ضروری ہے",
      needsConnectionBody: "آپ آف لائن ہیں۔ کنکشن بحال ہونے پر سائن آؤٹ کریں۔",
    },
  },
});
