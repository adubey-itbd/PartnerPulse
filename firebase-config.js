/* Firebase Web app config — PUBLIC values, safe to commit/serve.
 *
 * These identify the Firebase project to the browser SDK; they are NOT secrets.
 * Access is controlled by Firebase Auth (email/password restricted to @itbd.net,
 * email verification required) plus firestore.rules, which deny all reads until
 * email_verified is true — NOT by hiding these values. There is no Cloud Function
 * or Storage layer in front of the data; the browser reads Cloud Firestore
 * directly via the Web SDK (see auth.js).
 *
 * Fill them from: Firebase Console -> Project settings -> General ->
 * "Your apps" -> Web app -> SDK setup and configuration -> Config.
 *
 * While these still say REPLACE_ME (or when running on localhost), auth.js
 * stays in DEV mode: no sign-in, data read straight from data/<file>. So the
 * existing `python server.py` workflow keeps working unchanged.
 */
window.FIREBASE_CONFIG = {
  apiKey: "AIzaSyCTW8yRrpmJunhWuerm9Mo77GfPafqcb_M",
  authDomain: "operational-intelligence-ebe23.firebaseapp.com",
  projectId: "operational-intelligence-ebe23",
  storageBucket: "operational-intelligence-ebe23.firebasestorage.app",
  messagingSenderId: "614232052371",
  appId: "1:614232052371:web:8c98bcc3b60c28a394f366",
  measurementId: "G-LLW6ZL25QT",
};
