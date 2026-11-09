import { defineCatalog } from "../catalog";

/** Strings for the shared building blocks: error states, pagers, confirm dialogs. */
export const sharedMessages = defineCatalog({
  en: {
    noAccess: "You don't have access to this",
    couldntLoad: "Couldn't load this",
    requestId: "Request ID: {id}",
    tryAgain: "Try again",
    loading: "Loading",
    confirm: "Confirm",
    cancel: "Cancel",
    showing: "Showing {first}–{last} of {total}",
    previous: "Previous",
    next: "Next",
    pageOf: "Page {page} of {pages}",
    accountMenu: "Account menu",
    navigation: "Navigation",
    openNavigation: "Open navigation",
    closeNavigation: "Close navigation",
  },
  ur: {
    noAccess: "آپ کو اس تک رسائی نہیں ہے",
    couldntLoad: "یہ لوڈ نہیں ہو سکا",
    requestId: "درخواست نمبر: {id}",
    tryAgain: "دوبارہ کوشش کریں",
    loading: "لوڈ ہو رہا ہے",
    confirm: "تصدیق کریں",
    cancel: "منسوخ کریں",
    showing: "{total} میں سے {first}–{last}",
    previous: "پچھلا",
    next: "اگلا",
    pageOf: "صفحہ {page} از {pages}",
    accountMenu: "اکاؤنٹ مینو",
    navigation: "نیویگیشن",
    openNavigation: "مینو کھولیں",
    closeNavigation: "مینو بند کریں",
  },
});
