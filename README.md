# Tokatap

This application uses Flask. To enable password reset emails through Gmail, set the following environment variables:

- `GMAIL_USER` – your Gmail address used to send emails.
- `GMAIL_PASS` – the app password for the above account.

The feature uses a timed token so reset links expire after one hour.
