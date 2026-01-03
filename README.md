# Tokatap

## Runtime

The project is deployed with Python 3.12 to avoid compatibility issues seen with
newer runtimes (for example, some third-party libraries crash on Python 3.13).
Railway/Heroku style deployments can be pinned via `runtime.txt`.

Placeholder README for the Tokatap Flask application.

## Quickstart

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the development server:
   ```bash
   flask --app app run --debug
   ```

## Environment Variables

Create a `.env` file with the following variables:

```
SECRET_KEY=
DATABASE_URL=
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
```
