import type { MarketingCopy } from "./copy";

/** The public site in English. The source of truth; copy-ur.ts follows it. */
export const en: MarketingCopy = {
  common: {
    home: "Home",
    features: "Features",
    allFeatures: "All features",
    readMore: "Read more",
    howItWorks: "How it works",
    detailsLabel: "Details",
    questionsTitle: "Questions schools ask",
    questionsLede: {
      before: "Something else? ",
      link: "Start free",
      after: " and try it with your own classes.",
    },
    moreIn: "More in SchoolYar",
    alsoIncluded: "Also included",
    startFree: "Start free",
    seePricing: "See pricing",
    freeNote: "Free for one school and 50 students. No card required.",
    signIn: "Sign in",
    getStarted: "Get started",
    dashboard: "Dashboard",
    pricing: "Pricing",
    operatorConsole: "Operator console",
    menu: "Menu",
    tagline: "School management, from the diary to the fee challan",
    bookDemo: "Book a free demo",
    demoMessage: "Hello! I'd like a free demo of SchoolYar for our school.",
    talkOnWhatsApp: "Talk on WhatsApp",
    contactMessage: "Hello! I have a question about SchoolYar.",
  },

  nav: {
    product: "Product",
    support: "Support",
    platformGroup: "Platform",
    whyGroup: "Why SchoolYar",
    overview: { label: "Overview", body: "Every part of the school office, in one place" },
    tour: { label: "Product tour", body: "Watch the diary, challans and registers at work" },
    ai: { label: "AI that waits for OK", body: "Photos, messages and books turned into finished work" },
    why: { label: "Why schools choose us", body: "Nine reasons school offices switch" },
    security: { label: "Security and privacy", body: "Each organization's data isolated by the database" },
    roles: { label: "For every role", body: "Owners, teachers, accountants and parents" },
    start: {
      label: "Start in three steps",
      body: "Create your organization, add your classes, and turn on what you need. Free for one school and 50 students.",
    },
    aiGroup: "WhatsApp and AI",
    officeGroup: "School office",
    alsoLine: "Also included: admissions, exams and result cards, ID cards, search and an audit log.",
    faq: { label: "Questions schools ask", body: "Plain answers to what schools ask first" },
    pricingFaq: { label: "Plans and billing", body: "Limits, yearly plans and failed payments" },
    demo: { label: "Book a free demo", body: "We walk your team through it" },
    whatsapp: { label: "WhatsApp", body: "Chat with the SchoolYar team" },
    email: { label: "Email", body: "Write to the team" },
    phone: { label: "Phone", body: "Call the team" },
    signIn: { label: "Sign in", body: "Back to your school's panel" },
    announcement: { tag: "New", text: "Add a book from two photos of its cover and contents page" },
  },

  footer: {
    about:
      "School management for schools and school groups: fees and bank challans, attendance, exams, test papers from your own books, and a WhatsApp diary teachers send as a photo.",
    support: "Support",
    rights: "All rights reserved.",
    product: "Product",
    account: "Account",
    language: "Language",
    forgotPassword: "Forgot password",
    contact: "Contact",
    whatsapp: "WhatsApp",
    email: "Email",
    phone: "Phone",
  },

  home: {
    metaDescription:
      "School management software: bank fee challans, attendance registers, exams, test papers from your own textbooks, and a WhatsApp diary that teachers send as a photo. Free for one school.",
    hero: {
      title: { before: "School management that ", em: "does the typing", after: " for you." },
      lede: "Fees and bank challans, attendance, exams and test papers in one place, with AI that turns a photo of the class diary into a message for parents on WhatsApp. For one school or a whole group.",
      points: ["Free for one school", "Every screen in Urdu", "Ready for many campuses"],
    },
    dashboard: {
      description:
        "Example: a campus's SchoolYar dashboard, with 1,248 students, 82% of October's challans paid and 94% present today, a chart of fee collection over six months, and a live list of challans paid, diaries posted and registers submitted.",
      nav: ["Dashboard", "Students", "Fees", "Attendance", "Exams", "WhatsApp", "Test papers"],
      greeting: "Good morning",
      campus: "Main campus",
      search: "Search students, staff, challans",
      kpis: [
        ["Students", "1,248", "+36 this term"],
        ["Fees collected", "82%", "of October's challans"],
        ["Present today", "94%", "1,173 of 1,248"],
        ["Diaries posted", "32", "today, on WhatsApp"],
      ],
      chartTitle: "Fee collection",
      chartNote: "Challans paid, last six months",
      months: ["May", "Jun", "Jul", "Aug", "Sep", "Oct"],
      todayTitle: "Today's register",
      legend: ["Present", "Absent", "Late"],
      activityTitle: "Live activity",
      activity: [
        ["Challan 10482 paid", "just now"],
        ["Diary posted to 9-A parents", "2 min"],
        ["Register submitted · Nursery-A", "6 min"],
        ["Test paper drafted · Grade 7 Science", "14 min"],
        ["Late fee added to 18 challans", "1 hr"],
      ],
      callouts: [
        ["Diary posted", "9-A parents' group"],
        ["Challan paid", "No. 10482 · bank copy"],
        ["Register submitted", "28 present · 2 absent"],
      ],
    },
    ticker: "Everything a school office runs on",
    platform: {
      title: "One platform for the whole school office",
      lede: "Each part works on its own, and all of them share one list of students, classes and staff. Turn on what you need, when you need it.",
      more: "See all features",
    },
    tour: {
      title: "See SchoolYar at work",
      lede: "Pick a part of the school office and watch what it does.",
    },
    security: {
      title: "Online, secure and ready to grow",
      lede: "Run every campus from one account in the browser, with the walls in the right places.",
      points: [
        [
          "Nothing to install",
          "Staff use SchoolYar in the browser, on the office computer or a phone. There is no server for your school to keep.",
        ],
        [
          "Isolated by the database",
          "Each organization's data is kept apart by the database itself, not by a filter someone remembered to write.",
        ],
        [
          "WhatsApp built in",
          "Link a campus's WhatsApp number once, and the diary, attendance and fee notices run through it.",
        ],
        [
          "Roles and permissions",
          "Each person sees only what their role and campus allow, and revoking access takes effect immediately.",
        ],
        [
          "An audit log",
          "Payment reversals, register changes and role edits are recorded with who made them and when.",
        ],
      ],
      hub: ["Students", "Fees", "Attendance", "Exams", "Test papers", "WhatsApp", "Admissions", "ID cards"],
    },
    roles: {
      title: "Made for everyone in the school",
      lede: "One system, and each person sees the part that is theirs.",
      items: [
        {
          title: "Owners and principals",
          body: "Every campus at a glance, and the final word on changes.",
          points: [
            "Switch between campuses",
            "Approve changes to submitted registers",
            "Reverse a payment, with a recorded reason",
            "Build the roles your school uses",
          ],
        },
        {
          title: "Teachers",
          body: "Work from the phone already in their pocket.",
          points: [
            "Send the diary as a photo",
            "Take the register in one WhatsApp message",
            "Build test papers from the class's own books",
            "Mark registers on the web by date or period",
          ],
        },
        {
          title: "Accountants",
          body: "Challans, payments and ledgers without the arithmetic.",
          points: [
            "Issue a month's challans for a class or campus",
            "Record payments against each challan",
            "Concessions and late fees applied by rule",
            "A running ledger for every student",
          ],
        },
        {
          title: "Parents",
          body: "Nothing to install and nothing to learn.",
          points: [
            "The class diary in their WhatsApp group",
            "The month's fee and due date on WhatsApp",
            "A printed challan to pay at the bank",
            "An online admission form for each campus",
          ],
        },
      ],
    },
    numbers: {
      title: "SchoolYar in numbers",
      items: [
        [50, "students free, on one school"],
        [5, "attendance marks, not two"],
        [3, "challan copies on one page"],
        [100, "questions in a single test paper"],
      ],
    },
    why: {
      title: "Why school offices choose SchoolYar",
      lede: "Less retyping, fewer calculators, and nothing that runs without a person's OK.",
      items: [
        ["Free to start", "One school and 50 students cost nothing, and no card is needed."],
        ["Ready the same day", "Create your organization, add classes and invite staff in an afternoon."],
        ["Nothing to install", "Staff work in the browser; teachers use the WhatsApp they already have."],
        ["Your school's format", "Your challan design, your diary template and your own role names."],
        ["Grows with your group", "Add campuses as you open them, all in the same account."],
        ["Secure by design", "Data isolated by the database, and sensitive changes logged with a name."],
        ["People stay in charge", "AI drafts the work; nothing reaches parents or the register without OK."],
        ["Records never locked", "If a payment fails, the panel turns read-only. Nothing is deleted."],
        ["In your language", "Every screen in English or Urdu, chosen by each person."],
      ],
    },
    steps: ["Teacher sends a photo", "SchoolYar reads it", "Teacher checks it", "Parents get it"],
    pause: "Pause the demo",
    play: "Play the demo",
    demoDescription:
      "Demo: a teacher sends a photo of the class diary to the school's WhatsApp number. SchoolYar reads it and replies with the diary for Grade 9-A. The teacher adds a line, replies OK, and the diary is posted to the 9-A parents' group.",
    fees: {
      title: "Fee challans, printed the way your bank expects",
      lede: "Set up fee heads and class fee structures once. Every month SchoolYar issues each student's challan on the ruled bank-counter layout, with your account details and the copies your bank asks for.",
      facts: [
        [
          "Concessions that stay applied",
          "Concession schemes, per-student discounts and agreed rates apply every month without anyone re-entering them.",
        ],
        ["Late fees on their own", "Set the rule once. The late fee is added after the due date."],
        [
          "Arrears carried forward",
          "Every student has a running ledger, so last month's balance appears on this month's challan.",
        ],
        [
          "Stationery on the same challan",
          "Charge copies, books and uniform by quantity, next to the tuition fee.",
        ],
        ["A whole term on one page", "Print several months of a student's challans on a single sheet."],
        [
          "Fee notice on WhatsApp",
          "On your send day, every linked class group gets the month's fee and due date.",
        ],
      ],
      more: "More about fee management",
    },
    papers: {
      title: "Test papers from the textbooks you actually teach",
      lede: "Teachers upload each chapter as a PDF or as phone photos, in any order. SchoolYar reads every page, puts the pages in printed order, sets aside any page that belongs to another chapter, and makes the whole book searchable.",
      recipeLede:
        "Then a teacher picks the chapters and the mix of questions, and gets a draft paper to edit, swap questions in, and print.",
      recipe: ["Chapters 4 and 5", "10 MCQs", "5 short questions", "In Urdu or English"],
      draft: "Draft paper · 15 questions",
      more: "More about the test paper generator",
    },
    attendance: {
      title: "Mark the register. The percentages add up on their own.",
      lede: "Each section gets a register for every date and period. Teachers mark it; the office sees the totals.",
      facts: [
        [
          "Five marks, not two",
          "Present, absent, late, excused and half day, because a report card treats each one differently.",
        ],
        [
          "Percentages you can defend",
          "They count only the days a register was actually taken, so a holiday never drags a child's figure down.",
        ],
        [
          "History that survives promotion",
          "Promote a class in April and March's attendance stays with the class the student was in then.",
        ],
        [
          "Or by WhatsApp message",
          "A teacher texts \u201cNursery-A absent 12, 13\u201d to the school's number, checks the names that come back, and replies OK.",
        ],
      ],
      more: "More about attendance",
    },
    campuses: {
      title: "One account for every campus",
      lede: "Add schools as your group grows. Owners switch between campuses; staff see the campus they work at.",
      pillars: [
        [
          "Each campus keeps its own",
          "Staff, students, fee settings and challan design stay with the campus they belong to. Owners see them all.",
        ],
        [
          "Separation you can point to",
          "Each organization's data is isolated by the database itself, not by a filter someone remembered to write.",
        ],
        [
          "Roles that fit your school",
          "Start from Principal, Teacher and Accountant, then build the roles you actually use. Revoking access takes effect immediately.",
        ],
        [
          "Billing never locks your records",
          "If a subscription payment fails, the panel turns read-only. Your students' records stay readable.",
        ],
      ],
      more: "More about running several campuses",
    },
    urdu: {
      title: "Every screen works in Urdu too",
      lede: "Switch the language and the whole panel turns right to left, menus and tables included. Urdu test papers print in Nastaliq, the script children read at school.",
      more: "More about SchoolYar in Urdu",
    },
    yaar: {
      title: "Yaar means friend.",
      body: "SchoolYar is the friend in your school office. It does the retyping, the adding up and the reminding, so your staff can spend their time on the children.",
    },
    ai: {
      title: "AI that does the typing, then waits for your OK",
      lede: "Each one starts with something your staff already have: a photo, a message or a book. SchoolYar does the reading and the writing, and a person approves the result before it is used.",
      send: "You send",
      result: "You get",
      flows: [
        [
          "WhatsApp diary",
          "A photo of the paper diary",
          "The diary in your campus's format, posted to the class parents' group once the teacher replies OK",
        ],
        [
          "WhatsApp attendance",
          "\u201cNursery-A absent 12, 13\u201d",
          "The students' names shown back, and the register submitted once the teacher replies OK",
        ],
        [
          "A new book",
          "Photos of its cover and contents page",
          "Title, class, subject, publisher, edition and the chapter list, filled in for a teacher to check",
        ],
        [
          "Test papers",
          "The chapters to test, from your own books",
          "A draft paper with the questions you asked for, ready to edit and print",
        ],
      ],
    },
    start: {
      title: "Start in three steps",
      steps: [
        ["Create your organization", "Sign up free and add your first school. No card required."],
        [
          "Add classes and staff",
          "Set up classes and sections, add your students, and invite staff by email with the role each one needs.",
        ],
        [
          "Turn on what you need",
          "Link the school's WhatsApp number for the diary and attendance, set up fee heads for challans, and add your books for test papers.",
        ],
      ],
    },
    faqs: [
      [
        "Is there a free plan?",
        "Yes. One school with up to 50 students is free, with no card required. Paid plans add more students and campuses.",
      ],
      [
        "Do teachers or parents need to install an app?",
        "No. Staff use SchoolYar in the browser, and teachers send the diary and attendance from the WhatsApp they already have. Parents get the diary in their class's WhatsApp group.",
      ],
      [
        "Does the AI post anything on its own?",
        "No. The WhatsApp diary and attendance wait for the teacher's OK, and a book's details and every test paper are drafts a teacher checks before they are used.",
      ],
      [
        "Does it work in Urdu?",
        "Yes. Every screen works in Urdu, right to left, and each person picks their own language. Urdu test papers print in Nastaliq.",
      ],
      [
        "Can we run several campuses?",
        "Yes. One account holds every campus. Each keeps its own staff, students, fees and challan design, and owners see them all.",
      ],
      [
        "Is our data kept private?",
        "Each organization's data is isolated by the database itself, and changes to payments, registers and roles are recorded with who made them.",
      ],
    ],
    cta: {
      title: "Ready when you are",
      body: "Create your organization, add your first school, and invite your staff. It takes a few minutes.",
    },
  },

  featuresIndex: {
    metaTitle: "Features: fee challans, WhatsApp diary, test papers and attendance",
    metaDescription:
      "Everything SchoolYar does for a school: bank fee challans, a WhatsApp diary teachers send as a photo, test papers from your own textbooks, attendance registers, multiple campuses and Urdu.",
    title: "Everything SchoolYar does for your school",
    lede: "From the morning register to the monthly challan. Each part works on its own, and all of them share one list of students, classes and staff.",
  },

  pricing: {
    metaDescription:
      "SchoolYar is free for one school and 50 students, with no card required. Compare plans for more students and more campuses.",
    unavailable: "Plans are temporarily unavailable. Please try again shortly.",
    groups: {
      before: "Running a large school group? ",
      link: "Talk to us",
      after: " about a plan for every campus.",
    },
    faqs: [
      [
        "What does the free plan include?",
        "One school and up to 50 students, free, with no card required. The table above lists everything each plan includes.",
      ],
      ["Is paying yearly cheaper?", "Yes. A yearly plan costs the same as ten months, so two months are free."],
      [
        "What happens if we go over our plan's limits?",
        "Nothing is deleted and your existing records stay available. Adding new records pauses until you upgrade or are back under the limit.",
      ],
      [
        "What if a payment fails?",
        "The panel turns read-only until it is sorted out. Your records stay readable and nothing is deleted.",
      ],
      [
        "Can we change plans later?",
        "Yes. Change your plan from Billing in the panel whenever your school grows.",
      ],
    ],
  },

  authAside: {
    title: "Your school office, in one place",
    body: "Fees, attendance, exams and the WhatsApp diary share one list of students, classes and staff.",
    points: [
      "Free for one school and 50 students",
      "Every screen in English or Urdu",
      "Nothing posts without a person's OK",
    ],
  },

  alsoIncluded: [
    "An online admission form for each campus",
    "Exams, marks and result cards",
    "Student ID cards in your own design",
    "One search across students, staff and challans",
    "Staff invitations by email",
    "An audit log of who changed what",
  ],

  demos: {
    challan:
      "Example: a fee challan printed in three parts (bank copy, school copy and student copy), with the bank's PAID stamp on the school copy.",
    pages:
      "Example: six page photos of Chapter 4 uploaded in random order. SchoolYar sorts them into pages 37 to 41 and sets aside page 112, which belongs to Chapter 7, for a teacher to review.",
    register:
      "Example: the October register for Class 9-A, with present, absent and late marks for six students and each student's attendance percentage.",
    campus:
      "Example: one school group with three campuses, each with its own students, staff and bank accounts for challans.",
    attendanceChat:
      "Example: a teacher sends \u201cNursery-A absent 12, 13, 15\u201d to the school's WhatsApp number, gets the three names back, corrects one, replies OK, and the register is submitted with 28 present and 2 absent.",
  },

  features: {
    "whatsapp-diary": {
      nav: "WhatsApp diary",
      metaTitle: "WhatsApp school diary: teachers send a photo, parents get the homework",
      metaDescription:
        "Teachers photograph the paper diary and send it to the school's WhatsApp number. SchoolYar reads it, writes it in your campus's format, and posts it to the class parents' group once the teacher replies OK.",
      eyebrow: "WhatsApp diary for schools",
      h1: "The class diary, in the parents' group before the last bell",
      lede: "Teachers keep writing the diary on paper. They photograph the page and send it to the school's WhatsApp number. SchoolYar reads it, writes it in your campus's format, and posts it to the right class group once the teacher replies OK.",
      summary:
        "Teachers photograph the paper diary; parents get it in the class WhatsApp group once the teacher says OK.",
      steps: [
        [
          "Teacher sends a photo",
          "From their own phone, to the school's WhatsApp number. No app to install and no form to fill in.",
        ],
        [
          "SchoolYar reads the page",
          "It reads each subject and its homework, works out which class the page is for, and writes the diary in your campus's format.",
        ],
        [
          "Teacher checks it",
          "The finished message comes back to the teacher first. They reply OK, or type a correction in plain words.",
        ],
        [
          "Posted to the class group",
          "The diary goes to that class's parents' WhatsApp group, exactly as the teacher approved it.",
        ],
      ],
      detailsTitle: "Built so the wrong message never reaches parents",
      details: [
        [
          "Nothing posts without OK",
          "The diary is posted only after the teacher replies OK to the exact text they were shown.",
        ],
        [
          "Only your staff get an answer",
          "The school's number answers staff of that campus whose saved phone matches. Parents and strangers get no reply at all.",
        ],
        [
          "Only their own classes",
          "A teacher can post to the section they class-teach or the classes they teach a subject in. The AI suggests a class from that list and cannot pick one outside it.",
        ],
        [
          "Your format, every time",
          "Set the template once: school name, class, date and one line per subject. SchoolYar fills in the layout itself, so the preview is exactly what parents receive.",
        ],
        [
          "Replies the way teachers type",
          "OK, yes, post or a thumbs-up posts the diary, and so do the everyday words teachers type in their own language. Cancel or no discards it. Anything else is read as a correction.",
        ],
        [
          "Old drafts don't linger",
          "A new photo replaces an unfinished draft, and a draft nobody answers lapses after a few hours.",
        ],
      ],
      faqs: [
        [
          "Do teachers need to install an app?",
          "No. They use the WhatsApp they already have and send the photo to the school's number. Their phone number only needs to be saved on their staff account in SchoolYar.",
        ],
        [
          "What if the diary is read wrongly?",
          "The teacher sees the finished diary before anything is posted, and can reply with a correction in plain words as many times as needed. Nothing reaches parents until they reply OK.",
        ],
        [
          "Can a teacher post to a class they don't teach?",
          "No. The diary can only go to the class groups in that teacher's teaching scope, unless the school has given them permission to see every class.",
        ],
        [
          "Can Urdu homework stay in Urdu?",
          "Yes. Each campus can give the reader its own instructions, such as \"keep Urdu homework in Urdu\" or \"call Maths 'Mathematics'\".",
        ],
        [
          "What does the school need to set it up?",
          "A WhatsApp number for the campus, linked to SchoolYar once, that can post in each class's parents' group. After that, teachers just send photos.",
        ],
      ],
    },

    "whatsapp-attendance": {
      nav: "WhatsApp attendance",
      metaTitle: "WhatsApp attendance for schools: send roll numbers, the register is done",
      metaDescription:
        "Teachers text the class and the roll numbers of absent students to the school's WhatsApp number. SchoolYar shows the names back and submits the day's register when the teacher replies OK.",
      eyebrow: "WhatsApp attendance for schools",
      h1: "Take the register in one WhatsApp message",
      lede: "A teacher sends the class and the roll numbers of the children who are not simply present. SchoolYar matches the numbers to names, shows them back, and submits the day's register once the teacher replies OK.",
      summary: "Teachers text the class and roll numbers; the register is submitted once they confirm the names.",
      steps: [
        [
          "Send the class and roll numbers",
          "For example \u201cNursery-A absent 12, 13, 15\u201d, from the teacher's own WhatsApp to the school's number. Everyone not mentioned is present.",
        ],
        [
          "Check the names",
          "SchoolYar replies with the date, the names of the students marked absent, and how many are present.",
        ],
        [
          "Correct in plain words",
          "\u201c13 was present\u201d or \u201calso 17\u201d changes the list. Nothing is written until the teacher is happy with it.",
        ],
        ["Reply OK", "The register is marked and submitted in one go, and the teacher gets the day's totals."],
      ],
      detailsTitle: "Quick for teachers, careful with the register",
      details: [
        [
          "Several marks in one message",
          "Absent, late, leave and half day can all go in one message, such as \u201c5B absent 3 late 7 leave 9\u201d.",
        ],
        [
          "The way teachers type",
          "Roman Urdu such as ghair hazir, chutti and hazir works, and so do Urdu digits. \u201cAll present\u201d or \u201csab hazir\u201d marks the whole class present.",
        ],
        [
          "Names before anything is saved",
          "Roll numbers are matched to the class list in SchoolYar, and the teacher confirms the names. The AI never sees a student's name.",
        ],
        [
          "Only their own classes",
          "A teacher can mark only a class they teach. If they name a class they don't teach, SchoolYar asks rather than marking another one.",
        ],
        [
          "The same register as on screen",
          "A WhatsApp register is the same submitted register teachers mark on the web, so reports and percentages count it the same way.",
        ],
        [
          "Only your staff get an answer",
          "The school's number answers staff of that campus whose saved phone matches. Anyone else gets no reply at all.",
        ],
      ],
      faqs: [
        [
          "Which register does a WhatsApp message mark?",
          "Today's whole-day register for the class. Period registers and earlier dates are still marked on the web.",
        ],
        [
          "What if the teacher doesn't name the class?",
          "If they teach only one class, it is that class. Otherwise SchoolYar asks which one they mean.",
        ],
        [
          "Do teachers need to install an app?",
          "No. They use the WhatsApp they already have. Their phone number only needs to be saved on their staff account in SchoolYar.",
        ],
        [
          "Can a register be changed after OK?",
          "Only by a principal, with a reason, the same as a register submitted on the web. The change is logged with who made it.",
        ],
        [
          "Are parents told when a child is absent?",
          "Not yet. Absences are recorded in SchoolYar and appear in its attendance reports.",
        ],
      ],
    },

    "fee-management": {
      nav: "Fees & challans",
      metaTitle: "School fee management with bank challans, concessions and late fees",
      metaDescription:
        "Issue every student's monthly fee challan in the three-copy bank layout, with concessions, automatic late fees, arrears carried forward and a running ledger.",
      eyebrow: "Fee management for schools",
      h1: "Fee challans your bank accepts, without filling one by hand",
      lede: "Set up fee heads and class fee structures once. SchoolYar issues each student's challan every month on the ruled bank-counter layout, records payments against it, and keeps a running ledger of what every family owes.",
      summary: "Monthly bank challans in three copies, with concessions, late fees and arrears handled for you.",
      steps: [
        [
          "Set up fee heads and structures",
          "Tuition, exam, admission, stationery: define the heads, then what each class pays for each one.",
        ],
        [
          "Issue the month's challans",
          "Generate challans for a class or the whole campus. Concessions and agreed rates are applied as they are created.",
        ],
        [
          "Print them",
          "Bank, school and student copies on one page, with your account details and the amount payable after the due date.",
        ],
        [
          "Record payments",
          "Mark what was paid against each challan. Whatever is left stays on the student's ledger for next month.",
        ],
      ],
      detailsTitle: "The rules your office applies by hand today",
      details: [
        [
          "Concessions that stay applied",
          "Concession schemes, per-student discounts and agreed rates apply every month without anyone re-entering them.",
        ],
        [
          "Late fees by rule, not by memory",
          "Set a fixed amount or a percentage, a grace period and a cap. The same rule reaches every family, and letting one off is a recorded decision.",
        ],
        [
          "Arrears carried forward",
          "Every student has a running ledger, so an unpaid balance shows on the next challan.",
        ],
        [
          "Stationery and one-off charges",
          "Sell copies, books and uniform by quantity on the same challan, or add a fine or a re-exam fee.",
        ],
        ["A whole term on one page", "Print several months of a student's challans on a single sheet."],
        [
          "The amount in words",
          "Every challan prints the total in words, in lakh and crore, so nobody can change 1,700 to 4,700 with one pen stroke.",
        ],
        [
          "Separation of duties",
          "Accountants record payments. Only a principal can void a challan or reverse a payment, and both are logged with names.",
        ],
        [
          "Fee notice on WhatsApp",
          "On your send day, each linked class group gets the month's standard fee and due date, once a month.",
        ],
      ],
      faqs: [
        [
          "Will our bank accept the challan?",
          "It follows the ruled bank-counter layout banks already process: the account, the payer, the amount, the due date and the amount after it, in bank, school and student copies. Each campus chooses which copies print and which accounts appear, up to four.",
        ],
        [
          "Can we give sibling or staff discounts?",
          "Yes. Create concession schemes such as a sibling or staff discount and apply them to students, or set an agreed rate for one student. They apply to every challan issued afterwards.",
        ],
        [
          "How are late fees charged?",
          "You set one rule per academic year: a fixed amount or a percentage of what is outstanding, after a grace period, once or repeating weekly or monthly, with an optional cap. SchoolYar applies it to every overdue challan, so no family is fined by hand.",
        ],
        [
          "What happens to fees that are not paid?",
          "They stay on the student's ledger and are printed as the previous balance on the next challan. Nothing is lost when a new month starts.",
        ],
        [
          "Can anyone delete a payment?",
          "No. A principal can reverse a payment with a reason, and the reversal is recorded in the audit log with both names.",
        ],
        [
          "Can parents pay online?",
          "Not yet. Families pay at the bank counter with the printed challan, and the office records the payment in SchoolYar.",
        ],
      ],
    },

    "test-paper-generator": {
      nav: "Test papers",
      metaTitle: "Test paper generator from your school's own textbooks",
      metaDescription:
        "Upload your textbooks chapter by chapter as PDFs or phone photos. SchoolYar builds MCQ, short and long question papers from the chapters you pick, in English, Urdu or Arabic, ready to edit and print.",
      eyebrow: "Test paper generator",
      h1: "Test papers from the textbooks you actually teach",
      lede: "Teachers upload each chapter as a PDF or as phone photos, in any order. SchoolYar reads every page, and builds a draft paper from the chapters you pick, in the mix of questions you ask for.",
      summary:
        "Upload chapters as PDFs or photos, then build MCQ, short and long question papers from them in English or Urdu.",
      steps: [
        [
          "Add the book",
          "Photograph its cover and contents page, and SchoolYar fills in the title, class, subject, publisher, edition and chapter list for you to check. Or type them in.",
        ],
        [
          "Upload each chapter",
          "A PDF, or photos of the pages in any order. SchoolYar puts them in printed-page order and checks the upload really is that chapter.",
        ],
        [
          "Pick chapters and the mix",
          "Choose the chapters, which question types and how many of each, the language, the difficulty and the time allowed.",
        ],
        ["Edit and print", "Change any question, swap one for another, set the marks, then print the paper."],
      ],
      detailsTitle: "A paper builder that starts from your syllabus",
      details: [
        [
          "Objective, subjective or mixed",
          "MCQs, true or false and fill in the blanks; short and long questions; or a paper with both.",
        ],
        [
          "English, Urdu or Arabic",
          "Urdu papers print in Nastaliq and Arabic papers in Naskh, the scripts children read in their textbooks.",
        ],
        [
          "Pages put in order for you",
          "Photos taken out of order are sorted by printed page number, and a page from the wrong chapter is set aside for a teacher to check.",
        ],
        ["Searchable books", "Search every uploaded chapter by meaning, not only by exact words."],
        [
          "A book set up from two photos",
          "The cover and contents page are enough: SchoolYar reads the details and the chapter list, and suggests only your own classes and subjects to file it under.",
        ],
        [
          "Teachers stay in charge",
          "Every draft is a teacher's to edit before it prints. A chapter that needs attention is flagged, not quietly used.",
        ],
        [
          "Books stay for next year",
          "Next year's teachers use the same books and chapters. A new edition is added as a new book.",
        ],
      ],
      faqs: [
        [
          "Which books can we use?",
          "Any book your school teaches from: board textbooks, private publishers' books or your own notes. Upload each chapter as a PDF or as photos of its pages.",
        ],
        [
          "Do we need scanned PDFs?",
          "No. Phone photos work, taken in any order. A PDF that already contains text is read directly.",
        ],
        ["Can I make an Urdu paper?", "Yes. Choose Urdu as the paper's language and it prints right to left, in Nastaliq."],
        [
          "Can I change the questions?",
          "Yes. Edit any question's wording, options or answer, replace it with another, or remove it before you print.",
        ],
        ["How big can a paper be?", "Up to 100 questions in up to five sections, one section per question type."],
        [
          "Do we have to type in each book's chapter list?",
          "No. Upload photos or a PDF of the cover and contents pages and the chapter list is filled in for you. Check it, correct anything, and add the book.",
        ],
      ],
    },

    attendance: {
      nav: "Attendance",
      metaTitle: "Student attendance register with percentages you can trust",
      metaDescription:
        "Mark each section's register by date and period with five statuses. Attendance percentages count only the days a register was taken, and history stays correct after promotion.",
      eyebrow: "Attendance register for schools",
      h1: "Mark the register. The percentages add up on their own.",
      lede: "Each section gets a register for every date and period. Teachers mark it and submit it; the office sees the day's totals and every student's percentage without reaching for a calculator.",
      summary:
        "Registers by date and period, marked on screen or by WhatsApp message, with percentages that stay right after promotion.",
      steps: [
        ["Open the register", "Pick the section, the date and the period. Every enrolled student is already listed."],
        [
          "Mark and submit",
          "Present, absent, late, excused or half day. Submitting tells the office the register is complete.",
        ],
        [
          "Read the reports",
          "A daily overview across sections, and each student's percentage over any dates you choose.",
        ],
      ],
      detailsTitle: "A register you can stand behind",
      details: [
        [
          "Five marks, not two",
          "Present, absent, late, excused and half day, because a report card treats each one differently.",
        ],
        [
          "Percentages you can defend",
          "They count only the days a register was actually taken, so a holiday never drags a child's figure down.",
        ],
        [
          "History that survives promotion",
          "Promote a class in April and March's attendance stays with the class the student was in then.",
        ],
        [
          "Changes are signed for",
          "Only a principal can change a submitted register, with a reason, and the before and after are kept in the audit log.",
        ],
        ["Whole day or by period", "Take one register a day, or one per period for subject teachers."],
        ["Drafts don't count", "A register that hasn't been submitted stays out of every report."],
        [
          "Or send it on WhatsApp",
          "A teacher texts the class and roll numbers, such as \u201cNursery-A absent 12, 13\u201d, to the school's WhatsApp number. SchoolYar shows the names back and submits the register when the teacher replies OK.",
        ],
      ],
      faqs: [
        [
          "Can a teacher change attendance after submitting it?",
          "No. A submitted register can only be changed or reopened by a principal, who must give a reason. The change is logged with who made it.",
        ],
        [
          "Do holidays lower attendance percentages?",
          "No. Percentages are worked out from the registers actually taken, so a day the school was closed simply doesn't count.",
        ],
        [
          "Does late count as present?",
          "Late counts as attended for the percentage, and is still recorded separately so you can see who is regularly late.",
        ],
        [
          "Can teachers take attendance on WhatsApp?",
          "Yes. They send the class and the roll numbers of students who are absent, late or on leave to the school's WhatsApp number. SchoolYar replies with the names, and submits the register when the teacher replies OK.",
        ],
        [
          "Are parents told automatically when a child is absent?",
          "Not yet. Today absences are recorded and reported inside SchoolYar.",
        ],
      ],
    },

    "multi-campus": {
      nav: "Multi-campus",
      metaTitle: "Multi-campus school management for school groups",
      metaDescription:
        "Run every campus of your school group from one account. Each campus keeps its own staff, students, fees and challan design, with roles you define and each organization's data isolated by the database.",
      eyebrow: "For school groups",
      h1: "One account for every campus",
      lede: "Add schools as your group grows. Owners move between campuses; principals, teachers and accountants work in the campus they belong to.",
      summary: "Every campus in one account, each with its own staff, students, fees and challan design.",
      steps: [
        ["Create your organization", "Sign up once for the whole group. You are its owner."],
        ["Add each campus", "Its name and logo, and its own challan design and bank accounts."],
        [
          "Invite staff to their campus",
          "Each invitation sets a role and a campus. Staff see only what that role allows.",
        ],
      ],
      detailsTitle: "Room to grow, with the walls in the right places",
      details: [
        [
          "Each campus keeps its own",
          "Staff, students, fee settings and challan design stay with the campus they belong to. Owners see them all.",
        ],
        [
          "Separation you can point to",
          "Each organization's data is isolated by the database itself, not by a filter someone remembered to write.",
        ],
        [
          "Roles that fit your school",
          "Start from Principal, Teacher and Accountant, then build the roles you actually use. Revoking access takes effect immediately.",
        ],
        [
          "Billing never locks your records",
          "If a subscription payment fails, the panel turns read-only. Your students' records stay readable.",
        ],
        [
          "An audit log of who changed what",
          "Payment reversals, register changes and role edits are recorded with who did them and when.",
        ],
        ["An admission form per campus", "Each campus has its own online admission form to share with parents."],
      ],
      faqs: [
        [
          "Can one person work at two campuses?",
          "Yes. Staff who belong to more than one campus choose which one to work in after signing in.",
        ],
        [
          "Can a teacher at one campus see another campus's students?",
          "No. Staff, students and settings are scoped to the campus they belong to.",
        ],
        [
          "What happens if our subscription payment fails?",
          "The panel turns read-only until it is sorted out. Your records stay readable and nothing is deleted.",
        ],
        [
          "Is the free plan limited to one campus?",
          "Yes. The free plan covers one school and 50 students. Add your second campus on a paid plan.",
        ],
      ],
    },

    urdu: {
      nav: "Urdu",
      metaTitle: "School management software in Urdu, right to left",
      metaDescription:
        "Every SchoolYar screen works in Urdu with a true right-to-left layout. Urdu test papers print in Nastaliq, and the WhatsApp diary can keep Urdu homework in Urdu.",
      eyebrow: "Urdu school software",
      h1: "School software in Urdu, right to left",
      lede: "Switch the language and the whole panel turns right to left, menus and tables included. Urdu test papers print in Nastaliq, the script children read at school.",
      summary: "A full right-to-left Urdu interface, with test papers printed in Nastaliq.",
      detailsTitle: "Urdu that reads the way it should",
      details: [
        [
          "A real right-to-left layout",
          "Not translated labels on a left-to-right page: menus, tables and forms mirror, as they should.",
        ],
        [
          "Each person picks their language",
          "The accountant can work in English while a teacher uses Urdu. SchoolYar remembers each choice.",
        ],
        ["Nastaliq papers", "Urdu test papers print in Nastaliq; Arabic papers print in Naskh."],
        ["Urdu homework stays Urdu", "Tell the WhatsApp diary to keep Urdu homework in Urdu, and it will."],
        ["Names as you write them", "Class, subject and role names appear exactly as your school typed them."],
      ],
      faqs: [
        [
          "Can some staff use English and others Urdu?",
          "Yes. The language is a personal choice, so each person sees SchoolYar in the language they picked.",
        ],
        [
          "Is everything translated?",
          "All menus, buttons and messages are. Names your school types, such as classes and roles, are shown exactly as you wrote them.",
        ],
        [
          "Do Urdu papers print properly?",
          "Yes, in Nastaliq, with the line spacing Nastaliq needs so the letters never collide.",
        ],
      ],
    },
  },
};
