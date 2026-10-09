// What Agnez says at each step of the first-run walkthrough, one script per step and language. These are written to be
// heard, not read: short sentences, no numerals or symbols, steps named in words ("Step one").
// The audio is generated once from these lines by `node scripts/make-tour-audio.mjs` (ElevenLabs, Agnez's own voice) and
// served as static files from public/tour/audio/<lang>/<step>.mp3. Change a line here, then run the script again: it
// regenerates only the lines whose text changed.
// Kannada and Hindi need a native-speaker pass before release (docs/native-review.md), like the on-screen copy.
// The Hindi lines avoid gendered verb forms in the first person on purpose.

export const NARRATION = {
  en: {
    welcome: "Hi, I'm Agnez, the voice of GrowIt. Welcome. I'll show you around in about two minutes. First, which language should I use? Pick one below.",
    sidebar: 'This is your menu. Home, your campaigns and all your tools live here. Point at an icon to see its name.',
    start: "Start here, with your offer. Tell me what you're selling, out loud or by tapping, and I'll ask a few short questions in your language.",
    talk: 'Step one, Talk. Answer my questions by voice. Every answer is kept in your own words.',
    plan: 'Step two, Plan. Your answers become a plan, and every line shows where it came from. When the facts are right, lock them.',
    campaign: 'Step three, Campaign. Your posts, posters and messages appear exactly as they will look, checked against your locked facts.',
    dashboard: 'Step four, Dashboard. See what was sent, what was clicked and what was checked. Every number comes from the app, never from a guess.',
    mic: 'This is the microphone. Tap it any time to talk to me. You can start a campaign, change one, or open a screen, all by voice. I answer out loud, and nothing changes without your yes.',
    summary: 'This is your calendar. It shows what goes out when, and what needs you next.',
    notifications: 'Tap your name to see your notifications: orders from your website, likes and shares, scheduled emails, and my suggestions.',
    new: 'Have a new offer? Start another campaign from here at any time.',
    memory: 'Memory is what I know about your business: your menu, prices or timings. Add things yourself, and edit them any time.',
    settings: 'In Settings you add your Agnes key, and choose your voice options and colours. You can replay this tour from there whenever you like.',
    done: "That's the tour. You're ready. Start your first campaign now. It takes about two minutes.",
  },
  kn: {
    welcome: 'ನಮಸ್ಕಾರ! ನಾನು Agnez, GrowIt ನ ಧ್ವನಿ. ಸ್ವಾಗತ. ಸುಮಾರು ಎರಡು ನಿಮಿಷದಲ್ಲಿ ಆ್ಯಪ್ ಪರಿಚಯಿಸುತ್ತೇನೆ. ಮೊದಲು, ಯಾವ ಭಾಷೆಯಲ್ಲಿ ತೋರಿಸಲಿ? ಕೆಳಗಿನಿಂದ ಒಂದನ್ನು ಆರಿಸಿ.',
    sidebar: 'ಇದು ನಿಮ್ಮ ಮೆನು. ಮುಖಪುಟ, ನಿಮ್ಮ ಪ್ರಚಾರಗಳು ಮತ್ತು ಎಲ್ಲಾ ಉಪಕರಣಗಳು ಇಲ್ಲಿಯೇ ಇವೆ. ಹೆಸರು ನೋಡಲು ಐಕಾನ್ ಮೇಲೆ ಕರ್ಸರ್ ಇಡಿ.',
    start: 'ಇಲ್ಲಿಂದ ಪ್ರಾರಂಭಿಸಿ, ನಿಮ್ಮ ಆಫರ್‌ನಿಂದ. ನೀವು ಏನು ಮಾರುತ್ತೀರಿ ಎಂದು ಹೇಳಿ ಅಥವಾ ಟ್ಯಾಪ್ ಮಾಡಿ. ನಿಮ್ಮ ಭಾಷೆಯಲ್ಲಿ ಕೆಲವು ಸಣ್ಣ ಪ್ರಶ್ನೆಗಳನ್ನು ಕೇಳುತ್ತೇನೆ.',
    talk: 'ಮೊದಲ ಹೆಜ್ಜೆ, ಮಾತನಾಡಿ. ಪ್ರಶ್ನೆಗಳಿಗೆ ಧ್ವನಿಯಲ್ಲಿ ಉತ್ತರಿಸಿ. ಪ್ರತಿಯೊಂದು ಉತ್ತರ ನಿಮ್ಮದೇ ಮಾತುಗಳಲ್ಲಿ ಉಳಿಯುತ್ತದೆ.',
    plan: 'ಎರಡನೇ ಹೆಜ್ಜೆ, ಯೋಜನೆ. ನಿಮ್ಮ ಉತ್ತರಗಳು ಯೋಜನೆಯಾಗುತ್ತವೆ, ಮತ್ತು ಪ್ರತಿ ಸಾಲು ಎಲ್ಲಿಂದ ಬಂತು ಎಂದು ತೋರಿಸುತ್ತದೆ. ಮಾಹಿತಿ ಸರಿಯಾಗಿದ್ದರೆ ಅದನ್ನು ಲಾಕ್ ಮಾಡಿ.',
    campaign: 'ಮೂರನೇ ಹೆಜ್ಜೆ, ಪ್ರಚಾರ. ನಿಮ್ಮ ಪೋಸ್ಟ್‌ಗಳು, ಪೋಸ್ಟರ್‌ಗಳು ಮತ್ತು ಸಂದೇಶಗಳು ಕಳುಹಿಸಿದಾಗ ಕಾಣುವಂತೆಯೇ ಇಲ್ಲಿ ಕಾಣುತ್ತವೆ, ಮತ್ತು ನೀವು ಲಾಕ್ ಮಾಡಿದ ಮಾಹಿತಿಯೊಂದಿಗೆ ಪರಿಶೀಲಿಸಲಾಗಿರುತ್ತದೆ.',
    dashboard: 'ನಾಲ್ಕನೇ ಹೆಜ್ಜೆ, ಡ್ಯಾಶ್‌ಬೋರ್ಡ್. ಏನು ಕಳುಹಿಸಲಾಯಿತು, ಎಷ್ಟು ಕ್ಲಿಕ್ ಆಯಿತು, ಏನು ಪರಿಶೀಲಿಸಲಾಯಿತು ಎಂದು ನೋಡಿ. ಪ್ರತಿ ಸಂಖ್ಯೆ ಆ್ಯಪ್‌ನಿಂದಲೇ ಬರುತ್ತದೆ, ಅಂದಾಜಲ್ಲ.',
    mic: 'ಇದು ಮೈಕ್. ಯಾವಾಗ ಬೇಕಾದರೂ ಇದನ್ನು ಒತ್ತಿ ಮಾತನಾಡಿ. ಪ್ರಚಾರ ಪ್ರಾರಂಭಿಸುವುದು, ಬದಲಿಸುವುದು, ಅಥವಾ ಪರದೆ ತೆರೆಯುವುದು, ಎಲ್ಲವೂ ಧ್ವನಿಯಿಂದ ಆಗುತ್ತದೆ. ನಾನು ಗಟ್ಟಿಯಾಗಿ ಉತ್ತರಿಸುತ್ತೇನೆ, ಮತ್ತು ನಿಮ್ಮ ಒಪ್ಪಿಗೆ ಇಲ್ಲದೆ ಏನೂ ಬದಲಾಗುವುದಿಲ್ಲ.',
    summary: 'ಇದು ನಿಮ್ಮ ಕ್ಯಾಲೆಂಡರ್. ಯಾವುದು ಯಾವಾಗ ಹೋಗುತ್ತದೆ, ಮತ್ತು ಮುಂದೆ ನೀವು ಏನು ಮಾಡಬೇಕು ಎಂದು ಇಲ್ಲಿ ಕಾಣುತ್ತದೆ.',
    notifications: 'ನಿಮ್ಮ ಹೆಸರನ್ನು ಒತ್ತಿ, ಸೂಚನೆಗಳು ಕಾಣುತ್ತವೆ. ವೆಬ್‌ಸೈಟ್ ಆರ್ಡರ್‌ಗಳು, ಲೈಕ್ ಮತ್ತು ಶೇರ್‌ಗಳು, ನಿಗದಿತ ಇಮೇಲ್‌ಗಳು ಮತ್ತು GrowIt ಸಲಹೆಗಳು, ಎಲ್ಲವೂ ಇಲ್ಲಿ.',
    new: 'ಹೊಸ ಆಫರ್ ಇದೆಯೇ? ಯಾವಾಗ ಬೇಕಾದರೂ ಇಲ್ಲಿಂದಲೇ ಇನ್ನೊಂದು ಪ್ರಚಾರ ಪ್ರಾರಂಭಿಸಿ.',
    memory: 'ಮೆಮೊರಿಯಲ್ಲಿ ನಿಮ್ಮ ವ್ಯಾಪಾರದ ಬಗ್ಗೆ GrowIt ಗೆ ತಿಳಿದಿರುವುದು ಇರುತ್ತದೆ: ಮೆನು, ಬೆಲೆ ಅಥವಾ ಸಮಯ. ನೀವೇ ಸೇರಿಸಬಹುದು, ಯಾವಾಗ ಬೇಕಾದರೂ ತಿದ್ದಬಹುದು.',
    settings: 'ಸೆಟ್ಟಿಂಗ್ಸ್‌ನಲ್ಲಿ ನಿಮ್ಮ Agnes ಕೀ ಸೇರಿಸಿ, ಧ್ವನಿ ಮತ್ತು ಬಣ್ಣಗಳನ್ನು ಆರಿಸಿ. ಈ ಪರಿಚಯವನ್ನು ಅಲ್ಲಿಂದ ಯಾವಾಗ ಬೇಕಾದರೂ ಮತ್ತೆ ಪ್ರಾರಂಭಿಸಬಹುದು.',
    done: 'ಪರಿಚಯ ಮುಗಿಯಿತು. ನೀವು ಸಿದ್ಧರಾಗಿದ್ದೀರಿ. ನಿಮ್ಮ ಮೊದಲ ಪ್ರಚಾರವನ್ನು ಈಗಲೇ ಪ್ರಾರಂಭಿಸಿ. ಸುಮಾರು ಎರಡು ನಿಮಿಷ ಸಾಕು.',
  },
  hi: {
    welcome: 'नमस्ते! मैं Agnez हूँ, GrowIt की आवाज़। आपका स्वागत है। चलिए, लगभग दो मिनट में ऐप देखते हैं। पहले बताइए, किस भाषा में दिखाएँ? नीचे से एक चुनिए।',
    sidebar: 'यह आपका मेन्यू है। होम, आपके कैंपेन और सारे टूल यहीं हैं। नाम देखने के लिए आइकन पर कर्सर रखिए।',
    start: 'यहाँ से शुरू कीजिए, अपने ऑफ़र से। बोलकर या टैप करके बताइए कि आप क्या बेच रहे हैं। आपकी भाषा में कुछ छोटे सवाल पूछे जाएँगे।',
    talk: 'पहला कदम, बात करें। सवालों के जवाब बोलकर दीजिए। हर जवाब आपके अपने शब्दों में रखा जाता है।',
    plan: 'दूसरा कदम, प्लान। आपके जवाब एक प्लान बन जाते हैं, और हर लाइन बताती है कि वह कहाँ से आई। तथ्य सही हों, तो उन्हें लॉक कर दीजिए।',
    campaign: 'तीसरा कदम, कैंपेन। आपके पोस्ट, पोस्टर और मैसेज बिल्कुल वैसे ही दिखते हैं जैसे वे भेजे जाएँगे, और आपके लॉक किए तथ्यों से जाँचे जाते हैं।',
    dashboard: 'चौथा कदम, डैशबोर्ड। यहाँ देखिए क्या भेजा गया, कितने क्लिक आए, और क्या जाँचा गया। हर संख्या ऐप से आती है, अंदाज़े से नहीं।',
    mic: 'यह माइक है। कभी भी इसे दबाकर बात कीजिए। कैंपेन शुरू करना, बदलना या कोई स्क्रीन खोलना, सब बोलकर हो जाता है। जवाब ज़ोर से सुनाई देगा, और आपकी हाँ के बिना कुछ नहीं बदलता।',
    summary: 'यह आपका कैलेंडर है। इसमें दिखता है कि क्या कब जाएगा, और आगे आपको क्या करना है।',
    notifications: 'अपने नाम पर दबाइए, सूचनाएँ दिखेंगी। वेबसाइट के ऑर्डर, लाइक और शेयर, तय किए गए ईमेल और GrowIt के सुझाव, सब यहीं।',
    new: 'नया ऑफ़र है? कभी भी यहीं से दूसरा कैंपेन शुरू कीजिए।',
    memory: 'मेमोरी में वह है जो GrowIt आपके कारोबार के बारे में जानता है: मेन्यू, कीमतें या समय। आप खुद जोड़ सकते हैं और कभी भी बदल सकते हैं।',
    settings: 'सेटिंग्स में आप अपनी Agnes की कुंजी डालते हैं, आवाज़ और रंग चुनते हैं, और जब चाहें यह टूर वहीं से दोबारा शुरू कर सकते हैं।',
    done: 'टूर पूरा हुआ। आप तैयार हैं। अपना पहला कैंपेन अभी शुरू कीजिए। लगभग दो मिनट लगते हैं।',
  },
};
