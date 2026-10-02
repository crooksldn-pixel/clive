/**
 * Extends app.json with the one thing that cannot live there: Android push
 * needs Firebase's google-services.json, which exists only once the Firebase
 * project is made (SETUP.md, step 5). Until then the app builds without it.
 * On EAS the file comes from the GOOGLE_SERVICES_JSON file variable.
 */
const fs = require('fs');
const path = require('path');

module.exports = ({ config }) => {
  const local = path.join(__dirname, 'google-services.json');
  const file = process.env.GOOGLE_SERVICES_JSON || (fs.existsSync(local) ? './google-services.json' : undefined);
  return {
    ...config,
    android: { ...config.android, ...(file ? { googleServicesFile: file } : {}) },
  };
};
