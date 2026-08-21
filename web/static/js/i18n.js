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
      'nav.draft': 'Draft Application',
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

      'draft.section_your_details': 'YOUR DETAILS',
      'draft.label_full_name': 'Full Name',
      'draft.label_address': 'Mailing Address',
      'draft.label_phone': 'Phone Number',
      'draft.label_email': 'Email Address (Optional)',
      'draft.label_locality': 'Locality / Ward / Area',
      'draft.label_timeframe': 'Time Period',
      'draft.section_public_authority': 'PUBLIC AUTHORITY',
      'draft.label_department': 'Select Department / Public Authority',
      'draft.label_pio': 'Public Information Officer (Optional)',
      'draft.section_what_you_want': 'WHAT YOU WANT TO KNOW',
      'draft.max_words': 'Max 500 words',
      'draft.helper_text': 'Ask for specific documents, records, or orders. Do not ask for opinions or reasons (e.g., "Why was my application rejected?").',
      'draft.section_fee': 'FEE PAYMENT',
      'draft.generate_button': 'Generate Application',
      'draft.save_draft_button': 'Save Draft',
      'draft.preview_empty': 'Fill in the form and click "Generate Application" to see your drafted RTI application here.',

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

  window.RTISahayakI18n = {
    getLanguage: getLanguage,
    setLanguage: setLanguage,
  };

  var currentLang = getLanguage();
  applyTranslations(currentLang);
  wireMenus(currentLang);
})();
