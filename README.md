# Tokatap

This application uses Flask. To enable password reset emails through Gmail, set the following environment variables:

- `GMAIL_USER` – the Gmail address used to send emails.
- `GMAIL_PASS` – an app password for the above account.

If you have two-factor authentication enabled, generate an app password in your Google account security settings and assign it to `GMAIL_PASS`.

The feature uses a timed token so reset links expire after one hour.
