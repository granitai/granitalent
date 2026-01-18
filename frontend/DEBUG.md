# Debugging White Page Issue

If you see a white page at http://localhost:3000, try these steps:

1. **Check Browser Console** (Press F12)
   - Look for any red error messages
   - Check the Console tab for JavaScript errors
   - Check the Network tab to see if files are loading

2. **Restart the Dev Server**
   ```powershell
   # Stop any running dev server (Ctrl+C)
   # Then restart:
   cd frontend
   npm run dev
   ```

3. **Check if Port 3000 is Available**
   ```powershell
   netstat -ano | findstr :3000
   ```

4. **Clear Browser Cache**
   - Press Ctrl+Shift+Delete
   - Clear cached images and files
   - Or try in incognito/private mode

5. **Check for Build Errors**
   ```powershell
   cd frontend
   npm run build
   ```

6. **Verify Dependencies are Installed**
   ```powershell
   cd frontend
   npm install
   ```











