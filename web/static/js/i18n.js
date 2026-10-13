// Shared UI-chrome translation engine (Gate 12). Loaded on every page via
// base.html, after each page's own {% block scripts %}, so per-page
// listeners are already wired by the time this runs.
//
// Scope: nav links, the language pill itself, and the primary headings/
// labels/buttons on home, ask, and draft (the three pages a citizen
// actually reads/fills). Not every string on every page is covered (browse
// detail content, the telemetry modal, 404/500 body copy, footer legal
// pages) - those stay English. This is a deliberate, disclosed subset, not
// an attempt at full-site i18n.
//
// The Act's own text is never translated (see agent/drafter.py's
// LETTER_STRINGS docstring for why) - this file only ever touches static
// UI chrome, never corpus text or citation content.
(function () {
  var LANGS = ['en', 'hi', 'mr'];
  var LANG_NAMES = { en: 'English', hi: 'हिंदी', mr: 'मराठी' };
  var STORAGE_KEY = 'rtiSahayakLanguage';

  var TRANSLATIONS = {
    en: {
      'nav.home': 'Home',
      'nav.ask': 'Ask',
      'nav.draft': 'Draft application',
      'nav.browse': 'Browse the Act',
      'nav.track': 'Track',
      'nav.tagline': 'Grounded in RTI Act, 2005',

      'home.heading': 'Turn your problem into a grounded RTI application',
      'home.subtext': "Every procedural claim is grounded in the Act's text and cited by section.",
      'home.input_placeholder': 'e.g. My road repair complaint has been ignored for 3 months',
      'home.draft_button': 'Draft',
      'home.suggestion1': 'My road repair complaint has been ignored for months',
      'home.suggestion2': 'My ration card renewal is stuck with no update',
      'home.suggestion3': 'My pension payments have stopped without explanation',
      'home.suggestion4': 'My complaint to the municipal office was never addressed',
      'home.sample_link': 'See a sample application',
      'home.trust1': 'Section-level citations',
      'home.trust2': "Declines requests that aren't asking for a specific record",
      'home.trust3': 'Draft your RTI and export a ready-to-file PDF',

      'ask.heading': 'Ask about the RTI Act, 2005',
      'ask.subtext': "Answers come only from the Act's own text, with a section citation for every claim. If nothing in the Act answers your question, this says so instead of guessing.",
      'ask.input_placeholder': 'e.g. How many days does a PIO have to respond?',
      'ask.button': 'Ask',
      'ask.empty_state': "Ask a question about the RTI Act's procedure, rights, or exemptions.",

      'draft.section_your_details': 'Your details',
      'draft.label_full_name': 'Full name',
      'draft.label_address': 'Mailing address',
      'draft.label_phone': 'Phone number',
      'draft.label_email': 'Email address (optional)',
      'draft.label_locality': 'Locality / ward / area',
      'draft.label_timeframe': 'Time period',
      'draft.section_public_authority': 'Public authority',
      'draft.label_department': 'Select department / public authority',
      'draft.label_pio': 'Public Information Officer (optional)',
      'draft.section_what_you_want': 'What you want to know',
      'draft.max_words': 'Max 500 words',
      'draft.helper_text': 'Ask for specific documents, records, or orders. Do not ask for opinions or reasons (e.g., "Why was my application rejected?").',
      'draft.section_fee': 'Fee payment',
      'draft.generate_button': 'Generate application',
      'draft.save_draft_button': 'Save draft',
      'draft.preview_empty': 'Fill in the form and click "Generate application" to see your drafted RTI application here.',

      'ph.full_name': 'e.g. Ramesh Kumar',
      'ph.address': 'Complete address for correspondence',
      'ph.email': 'Included in the application if provided',
      'ph.locality': 'e.g. Kothrud, Ward 12',
      'ph.timeframe': 'e.g. last 3 months',
      'ph.public_authority': 'e.g. Pune Municipal Corporation',
      'ph.pio': 'Designation of the PIO (if known)',
      'ph.filing_subject': 'e.g. Road repair complaint records',
      'ph.filing_reference': 'If you have one',
      'ph.act_search': "Search the Act — try 'third party' or 'section 8'",

      'footer.legal': 'Legal Disclaimer',
      'footer.privacy': 'Privacy Policy',
      'footer.terms': 'Terms of Service',
      'footer.support': 'Contact Support',
    },
    hi: {
      'nav.home': 'होम',
      'nav.ask': 'पूछें',
      'nav.draft': 'आवेदन बनाएं',
      'nav.browse': 'अधिनियम देखें',
      'nav.track': 'ट्रैक करें',
      'nav.tagline': 'आरटीआई अधिनियम, 2005 पर आधारित',

      'home.heading': 'अपनी समस्या को एक प्रमाणित आरटीआई आवेदन में बदलें',
      'home.subtext': 'हर प्रक्रियात्मक दावा अधिनियम के पाठ पर आधारित है और अनुभाग के अनुसार उद्धृत है।',
      'home.input_placeholder': 'जैसे: मेरी सड़क मरम्मत की शिकायत 3 महीने से अनदेखी की जा रही है',
      'home.draft_button': 'ड्राफ्ट करें',
      'home.suggestion1': 'मेरी सड़क मरम्मत की शिकायत महीनों से अनदेखी की जा रही है',
      'home.suggestion2': 'मेरे राशन कार्ड नवीनीकरण में कोई प्रगति नहीं हो रही',
      'home.suggestion3': 'मेरी पेंशन बिना किसी स्पष्टीकरण के बंद हो गई है',
      'home.suggestion4': 'नगर निगम कार्यालय में मेरी शिकायत पर कभी ध्यान नहीं दिया गया',
      'home.sample_link': 'एक नमूना आवेदन देखें',
      'home.trust1': 'अनुभाग-स्तर उद्धरण',
      'home.trust2': 'विशिष्ट अभिलेख न मांगने वाले अनुरोधों को अस्वीकार करता है',
      'home.trust3': 'अपना आरटीआई ड्राफ्ट करें और फाइल करने के लिए तैयार पीडीएफ निर्यात करें',

      'ask.heading': 'आरटीआई अधिनियम, 2005 के बारे में पूछें',
      'ask.subtext': 'उत्तर केवल अधिनियम के अपने पाठ से आते हैं, हर दावे के लिए अनुभाग उद्धरण के साथ। यदि अधिनियम में आपके प्रश्न का उत्तर नहीं है, तो अनुमान लगाने के बजाय यही बताया जाता है।',
      'ask.input_placeholder': 'जैसे: पीआईओ को जवाब देने के लिए कितने दिन मिलते हैं?',
      'ask.button': 'पूछें',
      'ask.empty_state': 'आरटीआई अधिनियम की प्रक्रिया, अधिकारों या छूट के बारे में एक प्रश्न पूछें।',

      'draft.section_your_details': 'आपका विवरण',
      'draft.label_full_name': 'पूरा नाम',
      'draft.label_address': 'डाक पता',
      'draft.label_phone': 'फोन नंबर',
      'draft.label_email': 'ईमेल पता (वैकल्पिक)',
      'draft.label_locality': 'इलाका / वार्ड / क्षेत्र',
      'draft.label_timeframe': 'समय अवधि',
      'draft.section_public_authority': 'लोक प्राधिकरण',
      'draft.label_department': 'विभाग / लोक प्राधिकरण चुनें',
      'draft.label_pio': 'लोक सूचना अधिकारी (वैकल्पिक)',
      'draft.section_what_you_want': 'आप क्या जानना चाहते हैं',
      'draft.max_words': 'अधिकतम 500 शब्द',
      'draft.helper_text': 'विशिष्ट दस्तावेज़, अभिलेख या आदेश माँगें। राय या कारण न पूछें (जैसे, "मेरा आवेदन क्यों अस्वीकार किया गया?")।',
      'draft.section_fee': 'शुल्क भुगतान',
      'draft.generate_button': 'आवेदन तैयार करें',
      'draft.save_draft_button': 'ड्राफ्ट सहेजें',
      'draft.preview_empty': 'फ़ॉर्म भरें और अपना ड्राफ्ट किया गया आरटीआई आवेदन यहाँ देखने के लिए "आवेदन तैयार करें" पर क्लिक करें।',

      'ph.full_name': 'उदा. रमेश कुमार',
      'ph.address': 'पत्राचार के लिए पूरा पता',
      'ph.email': 'दिए जाने पर आवेदन में शामिल किया जाएगा',
      'ph.locality': 'उदा. कोथरूड, वार्ड 12',
      'ph.timeframe': 'उदा. पिछले 3 महीने',
      'ph.public_authority': 'उदा. पुणे महानगरपालिका',
      'ph.pio': 'जन सूचना अधिकारी का पदनाम (यदि ज्ञात हो)',
      'ph.filing_subject': 'उदा. सड़क मरम्मत शिकायत के अभिलेख',
      'ph.filing_reference': 'यदि आपके पास हो',
      'ph.act_search': "अधिनियम में खोजें — जैसे 'third party' या 'section 8'",

      'footer.legal': 'कानूनी अस्वीकरण',
      'footer.privacy': 'गोपनीयता नीति',
      'footer.terms': 'सेवा की शर्तें',
      'footer.support': 'सहायता से संपर्क करें',
    },
    mr: {
      'nav.home': 'मुख्यपृष्ठ',
      'nav.ask': 'विचारा',
      'nav.draft': 'अर्ज तयार करा',
      'nav.browse': 'कायदा पहा',
      'nav.track': 'ट्रॅक करा',
      'nav.tagline': 'आरटीआय अधिनियम, 2005 वर आधारित',

      'home.heading': 'तुमच्या समस्येचे रूपांतर एका सुस्थापित आरटीआय अर्जात करा',
      'home.subtext': 'प्रत्येक प्रक्रियात्मक दावा कायद्याच्या मजकुरावर आधारित आहे आणि कलमानुसार उद्धृत केला आहे.',
      'home.input_placeholder': 'उदा: माझी रस्ता दुरुस्तीची तक्रार 3 महिन्यांपासून दुर्लक्षित आहे',
      'home.draft_button': 'मसुदा तयार करा',
      'home.suggestion1': 'माझी रस्ता दुरुस्तीची तक्रार महिन्यांपासून दुर्लक्षित आहे',
      'home.suggestion2': 'माझ्या रेशन कार्ड नूतनीकरणात कोणतीही प्रगती नाही',
      'home.suggestion3': 'माझी पेन्शन कोणत्याही स्पष्टीकरणाशिवाय बंद झाली आहे',
      'home.suggestion4': 'महानगरपालिका कार्यालयातील माझ्या तक्रारीकडे कधीच लक्ष दिले गेले नाही',
      'home.sample_link': 'नमुना अर्ज पहा',
      'home.trust1': 'कलम-स्तरीय उद्धरणे',
      'home.trust2': 'विशिष्ट अभिलेखाची मागणी नसलेले अर्ज नाकारते',
      'home.trust3': 'तुमचा आरटीआय मसुदा तयार करा आणि दाखल करण्यासाठी तयार पीडीएफ मिळवा',

      'ask.heading': 'आरटीआय अधिनियम, 2005 बद्दल विचारा',
      'ask.subtext': 'उत्तरे फक्त कायद्याच्या स्वतःच्या मजकुरातून येतात, प्रत्येक दाव्यासाठी कलम उद्धरणासह. जर कायद्यात तुमच्या प्रश्नाचे उत्तर नसेल, तर अंदाज न बांधता तसे सांगितले जाते.',
      'ask.input_placeholder': 'उदा: पीआयओला उत्तर देण्यासाठी किती दिवस मिळतात?',
      'ask.button': 'विचारा',
      'ask.empty_state': 'आरटीआय अधिनियमाची प्रक्रिया, हक्क किंवा सवलतींबद्दल प्रश्न विचारा.',

      'draft.section_your_details': 'तुमचा तपशील',
      'draft.label_full_name': 'पूर्ण नाव',
      'draft.label_address': 'टपाल पत्ता',
      'draft.label_phone': 'फोन नंबर',
      'draft.label_email': 'ईमेल पत्ता (ऐच्छिक)',
      'draft.label_locality': 'परिसर / प्रभाग / क्षेत्र',
      'draft.label_timeframe': 'कालावधी',
      'draft.section_public_authority': 'सार्वजनिक प्राधिकरण',
      'draft.label_department': 'विभाग / सार्वजनिक प्राधिकरण निवडा',
      'draft.label_pio': 'जन माहिती अधिकारी (ऐच्छिक)',
      'draft.section_what_you_want': 'तुम्हाला काय जाणून घ्यायचे आहे',
      'draft.max_words': 'जास्तीत जास्त 500 शब्द',
      'draft.helper_text': 'विशिष्ट कागदपत्रे, अभिलेख किंवा आदेश मागा. मत किंवा कारणे विचारू नका (उदा., "माझा अर्ज का नाकारला गेला?").',
      'draft.section_fee': 'शुल्क भरणा',
      'draft.generate_button': 'अर्ज तयार करा',
      'draft.save_draft_button': 'मसुदा जतन करा',
      'draft.preview_empty': 'फॉर्म भरा आणि तुमचा तयार केलेला आरटीआय अर्ज येथे पाहण्यासाठी "अर्ज तयार करा" वर क्लिक करा.',

      'ph.full_name': 'उदा. रमेश कुमार',
      'ph.address': 'पत्रव्यवहारासाठी संपूर्ण पत्ता',
      'ph.email': 'दिल्यास अर्जात समाविष्ट केला जाईल',
      'ph.locality': 'उदा. कोथरूड, प्रभाग 12',
      'ph.timeframe': 'उदा. मागील 3 महिने',
      'ph.public_authority': 'उदा. पुणे महानगरपालिका',
      'ph.pio': 'जन माहिती अधिकाऱ्याचे पदनाम (माहीत असल्यास)',
      'ph.filing_subject': 'उदा. रस्ता दुरुस्ती तक्रारीचे अभिलेख',
      'ph.filing_reference': 'तुमच्याकडे असल्यास',
      'ph.act_search': "कायद्यात शोधा — उदा. 'third party' किंवा 'section 8'",

      'footer.legal': 'कायदेशीर अस्वीकरण',
      'footer.privacy': 'गोपनीयता धोरण',
      'footer.terms': 'सेवा अटी',
      'footer.support': 'सहाय्य संपर्क',
    },
  };

  function getLanguage() {
    try {
      var stored = localStorage.getItem(STORAGE_KEY);
      return LANGS.indexOf(stored) !== -1 ? stored : 'en';
    } catch (e) {
      return 'en';
    }
  }

  function applyTranslations(lang) {
    var dict = TRANSLATIONS[lang] || TRANSLATIONS.en;
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      if (dict[key]) {
        el.textContent = dict[key];
      }
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      var key = el.getAttribute('data-i18n-placeholder');
      if (dict[key]) {
        el.setAttribute('placeholder', dict[key]);
      }
    });
    document.documentElement.setAttribute('lang', lang === 'en' ? 'en' : lang);

    // The pill's raw markup always starts as the static "English / हिंदी /
    // मराठी" label - once JS runs, it shows only the currently-active
    // language, with a caret hinting it opens a menu (see renderLangMenu).
    var pill = document.getElementById('lang-pill');
    if (pill) {
      pill.textContent = LANG_NAMES[lang] + ' ▾';
    }
    if (typeof applyPhrases === 'function') {
      applyPhrases(lang);
    }
  }

  // The lang-pill's dropdown menu reuses whatever tooltip span already sits
  // next to it in each page's markup (id="lang-note") - its content gets
  // replaced with real language options here rather than every template
  // needing new markup.
  function renderLangMenu(noteEl, current, onPick) {
    noteEl.innerHTML = '';
    noteEl.classList.remove('italic');
    LANGS.forEach(function (code) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = LANG_NAMES[code];
      btn.className = 'block w-full text-left px-sm py-xs rounded hover:bg-surface-container-low transition-colors ' +
        (code === current ? 'font-bold text-primary' : 'text-on-surface-variant');
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        onPick(code);
        noteEl.classList.add('hidden');
      });
      noteEl.appendChild(btn);
    });
  }

  function setLanguage(lang) {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) {
      // localStorage unavailable (private browsing, blocked site data) -
      // the selection just won't persist across page loads.
    }
    applyTranslations(lang);
    wireMenus(lang);
    window.dispatchEvent(new CustomEvent('rtisahayak:languagechange', { detail: { language: lang } }));
  }

  function wireMenus(current) {
    var note = document.getElementById('lang-note');
    if (note) {
      renderLangMenu(note, current, setLanguage);
    }
  }

  // ---- Phrase translation: everything not tagged with data-i18n ----
  // English UI text in text nodes and in placeholder/title/aria-label is
  // looked up in window.RTI_PHRASES (static/js/phrases.js); strings with a
  // variable part (section numbers, dates, counts, error details) go through
  // PATTERNS. Each node's English original is remembered, so switching back to
  // English restores it, and a MutationObserver translates text that page
  // scripts add later. Unknown strings are left as they are - that's how the
  // Act's own text, generated letters and user data stay untouched.
  var PHRASES = window.RTI_PHRASES || {};
  var LANG_INDEX = { hi: 0, mr: 1 };
  var activeLang = 'en';
  var SKIP = 'script, style, noscript, textarea, code, .material-symbols-outlined, [data-i18n], ' +
    '[data-i18n-skip], [data-title-el], #preview-content, #answer-content, #lang-pill, #lang-note';
  var ATTRS = ['placeholder', 'title', 'aria-label'];

  var SECTION = { hi: 'धारा', mr: 'कलम' };
  var PAGE = 'पृ.';
  var DISTANCE = { hi: 'दूरी', mr: 'अंतर' };
  var MONTHS = {
    hi: { Jan: 'जन॰', Feb: 'फ़र॰', Mar: 'मार्च', Apr: 'अप्रैल', May: 'मई', Jun: 'जून', Jul: 'जुल॰', Aug: 'अग॰', Sep: 'सित॰', Oct: 'अक्तू॰', Nov: 'नव॰', Dec: 'दिस॰' },
    mr: { Jan: 'जाने.', Feb: 'फेब्रु.', Mar: 'मार्च', Apr: 'एप्रि.', May: 'मे', Jun: 'जून', Jul: 'जुलै', Aug: 'ऑग.', Sep: 'सप्टें.', Oct: 'ऑक्टो.', Nov: 'नोव्हें.', Dec: 'डिसें.' },
  };
  function months(s, l) {
    return s.replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/g, function (m) { return MONTHS[l][m]; });
  }
  function pick(l, hi, mr) { return l === 'hi' ? hi : mr; }
  function prefixed(hi, mr) {
    return function (m, l) { return pick(l, hi, mr) + m[1]; };
  }
  var STRENGTH = {
    hi: { Weak: 'कमज़ोर', Fair: 'ठीक-ठाक', Good: 'अच्छा', Strong: 'मज़बूत' },
    mr: { Weak: 'कमकुवत', Fair: 'ठीक', Good: 'चांगला', Strong: 'मजबूत' },
  };

  var PATTERNS = [
    [/^Section (\d+[A-Z]?(?:\([0-9a-z]+\))*)$/, function (m, l) { return SECTION[l] + ' ' + m[1]; }],
    [/^Section (\S+) · p\.(\d+) · distance ([\d.]+)$/, function (m, l) { return SECTION[l] + ' ' + m[1] + ' · ' + PAGE + ' ' + m[2] + ' · ' + DISTANCE[l] + ' ' + m[3]; }],
    [/^p\.(\d+) · distance ([\d.]+)$/, function (m, l) { return PAGE + ' ' + m[1] + ' · ' + DISTANCE[l] + ' ' + m[2]; }],
    [/^p\.(\d+) · (\S+\.pdf)$/, function (m) { return PAGE + ' ' + m[1] + ' · ' + m[2]; }],
    [/^Search results for "(.*)"$/, function (m, l) { return pick(l, '"' + m[1] + '" के लिए खोज परिणाम', '"' + m[1] + '" साठी शोध परिणाम'); }],
    [/^Served by (.+)$/, function (m, l) { return pick(l, m[1] + ' द्वारा तैयार', m[1] + ' द्वारे तयार'); }],
    [/^Saved (.+?) · (Letter generated|Form only)$/, function (m, l) {
      var kind = m[2] === 'Letter generated' ? pick(l, 'पत्र तैयार', 'पत्र तयार') : pick(l, 'केवल फ़ॉर्म', 'फक्त फॉर्म');
      return pick(l, 'सहेजा गया: ', 'जतन: ') + months(m[1], l) + ' · ' + kind;
    }],
    [/^Due (.+)$/, function (m, l) { return pick(l, 'अंतिम तिथि: ', 'अंतिम तारीख: ') + months(m[1], l); }],
    [/^(.*) · Filed (.+)$/, function (m, l) { return m[1] + ' · ' + pick(l, 'दाखिल: ', 'दाखल: ') + months(m[2], l); }],
    [/^Overdue by (\d+) days?$/, function (m, l) { return pick(l, m[1] + ' दिन की देरी', m[1] + ' दिवस उशीर'); }],
    [/^(\d+) days? remaining - urgent$/, function (m, l) { return pick(l, m[1] + ' दिन शेष - तत्काल', m[1] + ' दिवस शिल्लक - तातडीचे'); }],
    [/^(\d+) days? remaining$/, function (m, l) { return pick(l, m[1] + ' दिन शेष', m[1] + ' दिवस शिल्लक'); }],
    [/^© (\d{4}) RTI Sahayak\. (.+)$/, function (m, l) { var rest = PHRASES[m[2]]; return '© ' + m[1] + ' RTI Sahayak. ' + (rest ? rest[LANG_INDEX[l]] : m[2]); }],
    [/^Welcome back, (.+)\. Pick up where you left off\.$/, function (m, l) { return pick(l, 'फिर से स्वागत है, ' + m[1] + '। जहाँ छोड़ा था वहीं से शुरू करें।', 'पुन्हा स्वागत आहे, ' + m[1] + '. जिथे थांबला होता तिथून सुरू करा.'); }],
    [/^Could not draft the application: (.*)$/, prefixed('आवेदन तैयार नहीं हो सका: ', 'अर्ज तयार होऊ शकला नाही: ')],
    [/^Could not download the PDF: (.*)$/, prefixed('पीडीएफ डाउनलोड नहीं हो सका: ', 'पीडीएफ डाउनलोड होऊ शकली नाही: ')],
    [/^Could not copy the text: (.*)$/, prefixed('टेक्स्ट कॉपी नहीं हो सका: ', 'मजकूर कॉपी होऊ शकला नाही: ')],
    [/^Could not get an answer: (.*)$/, prefixed('उत्तर नहीं मिल सका: ', 'उत्तर मिळू शकले नाही: ')],
    [/^Could not load statutory deadlines: (.*)\. Filings are still saved, but deadlines cannot be shown right now\.$/, function (m, l) {
      return pick(l, 'वैधानिक समय-सीमाएं लोड नहीं हो सकीं: ' + m[1] + '। फाइलिंग सहेजी हुई हैं, लेकिन अभी समय-सीमाएं नहीं दिखाई जा सकतीं।',
        'वैधानिक मुदती लोड होऊ शकल्या नाहीत: ' + m[1] + '. प्रकरणे जतन आहेत, पण सध्या मुदती दाखवता येत नाहीत.');
    }],
    [/^Could not verify (.+) in the retrieved grounding text - this deadline is omitted rather than shown unverified\.$/, function (m, l) {
      return pick(l, 'प्राप्त आधार पाठ में ' + m[1] + ' की पुष्टि नहीं हो सकी - इसलिए यह समय-सीमा बिना पुष्टि के दिखाने के बजाय छोड़ दी गई है।',
        'मिळालेल्या आधार मजकुरात ' + m[1] + ' ची पडताळणी होऊ शकली नाही - म्हणून ही मुदत पडताळणीशिवाय दाखवण्याऐवजी वगळली आहे.');
    }],
    [/^Couldn't reach (.+)\. Please try again\.$/, function (m, l) { return pick(l, m[1] + ' से संपर्क नहीं हो सका। कृपया फिर कोशिश करें।', m[1] + ' शी संपर्क होऊ शकला नाही. कृपया पुन्हा प्रयत्न करा.'); }],
    [/^Your (.+) account has no verified email address\.$/, function (m, l) { return pick(l, 'आपके ' + m[1] + ' खाते में कोई सत्यापित ईमेल पता नहीं है।', 'तुमच्या ' + m[1] + ' खात्यात सत्यापित ईमेल पत्ता नाही.'); }],
    [/^(Weak|Fair|Good|Strong)( - use at least 8 characters)?$/, function (m, l) {
      return STRENGTH[l][m[1]] + (m[2] ? pick(l, ' - कम से कम 8 अक्षर रखें', ' - किमान 8 अक्षरे वापरा') : '');
    }],
    [/^This backup contains (\d+) filing\(s\) and (\d+) draft\(s\)(?: \(saved (.+?)\))?\. Merge with what's already on this device, or replace it entirely\?$/, function (m, l) {
      var saved = m[3] ? pick(l, ' (सहेजा गया ' + m[3] + ')', ' (जतन ' + m[3] + ')') : '';
      return pick(l, 'इस बैकअप में ' + m[1] + ' फाइलिंग और ' + m[2] + ' ड्राफ्ट हैं' + saved + '। इस डिवाइस पर पहले से मौजूद डेटा के साथ मिलाएं, या उसे पूरी तरह बदल दें?',
        'या बॅकअपमध्ये ' + m[1] + ' प्रकरणे आणि ' + m[2] + ' मसुदे आहेत' + saved + '. या डिव्हाइसवरील विद्यमान डेटामध्ये विलीन करायचे, की तो पूर्णपणे बदलायचा?');
    }],
    [/^(Replaced existing data\.|Merged\.) (\d+) filing\(s\) imported(?: \((\d+) skipped as duplicates\))?, (\d+) draft\(s\) imported(?: \((\d+) skipped as duplicates\))?\.$/, function (m, l) {
      var replaced = m[1].indexOf('Replaced') === 0;
      if (l === 'hi') {
        return (replaced ? 'मौजूदा डेटा बदल दिया गया। ' : 'मिला दिया गया। ') + m[2] + ' फाइलिंग आयात की गईं' +
          (m[3] ? ' (' + m[3] + ' डुप्लिकेट होने से छोड़ी गईं)' : '') + ', ' + m[4] + ' ड्राफ्ट आयात किए गए' +
          (m[5] ? ' (' + m[5] + ' डुप्लिकेट होने से छोड़े गए)' : '') + '।';
      }
      return (replaced ? 'विद्यमान डेटा बदलला. ' : 'विलीन केले. ') + m[2] + ' प्रकरणे आयात केली' +
        (m[3] ? ' (' + m[3] + ' डुप्लिकेट म्हणून वगळली)' : '') + ', ' + m[4] + ' मसुदे आयात केले' +
        (m[5] ? ' (' + m[5] + ' डुप्लिकेट म्हणून वगळले)' : '') + '.';
    }],
  ];

  function phrase(text, lang) {
    var hit = PHRASES[text];
    if (hit) { return hit[LANG_INDEX[lang]]; }
    for (var i = 0; i < PATTERNS.length; i++) {
      var m = text.match(PATTERNS[i][0]);
      if (m) { return PATTERNS[i][1](m, lang); }
    }
    return null;
  }

  // English original -> string in `lang` (the original itself if unknown).
  function translateString(original, lang) {
    if (lang === 'en' || !original) { return original; }
    var core = original.replace(/\s+/g, ' ').trim();
    if (!core) { return original; }
    var out = phrase(core, lang);
    if (out === null) { return original; }
    return (/^\s/.test(original) ? ' ' : '') + out + (/\s$/.test(original) ? ' ' : '');
  }

  // Per node/attribute: the English original, and the last value written,
  // so a later change by a page script is recognised as a new original.
  var ORIG = new WeakMap();
  var LAST = new WeakMap();

  function translateText(node, lang) {
    var parent = node.parentElement;
    if (!parent || parent.closest(SKIP)) { return; }
    var current = node.nodeValue;
    var orig = ORIG.get(node);
    if (orig === undefined || LAST.get(node) !== current) { orig = current; ORIG.set(node, orig); }
    var out = translateString(orig, lang);
    if (out !== current) { node.nodeValue = out; }
    LAST.set(node, out);
  }

  function translateAttr(el, attr, lang) {
    if (!el.hasAttribute(attr) || el.closest('#lang-pill, #lang-note, [data-i18n-skip]')) { return; }
    if (attr === 'placeholder' && el.hasAttribute('data-i18n-placeholder')) { return; }
    var current = el.getAttribute(attr);
    var origs = ORIG.get(el) || {};
    var lasts = LAST.get(el) || {};
    if (origs[attr] === undefined || lasts[attr] !== current) { origs[attr] = current; }
    var out = translateString(origs[attr], lang);
    if (out !== current) { el.setAttribute(attr, out); }
    lasts[attr] = out;
    ORIG.set(el, origs);
    LAST.set(el, lasts);
  }

  function translateTree(root, lang) {
    if (root.nodeType === 3) { translateText(root, lang); return; }
    if (root.nodeType !== 1) { return; }
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var n;
    while ((n = walker.nextNode())) { translateText(n, lang); }
    var els = [root].concat(Array.prototype.slice.call(root.querySelectorAll('[placeholder], [title], [aria-label]')));
    els.forEach(function (el) {
      ATTRS.forEach(function (a) { if (el.hasAttribute && el.hasAttribute(a)) { translateAttr(el, a, lang); } });
    });
  }

  var ORIGINAL_TITLE = document.title;
  function translateTitle(lang) {
    // "Page - RTI Sahayak", or the home page's "RTI Sahayak - Home"
    var m = ORIGINAL_TITLE.match(/^(.+) - RTI Sahayak$/) || ORIGINAL_TITLE.match(/^RTI Sahayak - (.+)$/);
    document.title = m ? ORIGINAL_TITLE.replace(m[1], translateString(m[1], lang)) : ORIGINAL_TITLE;
  }

  var observer = new MutationObserver(function (records) {
    observer.disconnect(); // our own writes below must not re-trigger this
    records.forEach(function (r) {
      if (r.type === 'childList') {
        r.addedNodes.forEach(function (node) { translateTree(node, activeLang); });
      } else if (r.type === 'characterData') {
        translateText(r.target, activeLang);
      } else if (r.type === 'attributes') {
        translateAttr(r.target, r.attributeName, activeLang);
      }
    });
    observe();
  });
  function observe() {
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }

  function applyPhrases(lang) {
    activeLang = lang;
    observer.disconnect();
    translateTree(document.body, lang);
    translateTitle(lang);
    observe();
  }

  window.RTISahayakI18n = {
    getLanguage: getLanguage,
    setLanguage: setLanguage,
    // English UI string -> current language (for text that never enters the
    // DOM, e.g. setCustomValidity messages).
    t: function (english) { return translateString(english, activeLang); },
  };

  var currentLang = getLanguage();
  applyTranslations(currentLang);
  wireMenus(currentLang);
})();
