import { bootstrapApplication } from '@angular/platform-browser';
import { provideHttpClient } from '@angular/common/http';
import { App } from './app/app';

bootstrapApplication(App, {providers: [provideHttpClient()]})
  .catch(() => { document.body.textContent = 'No se pudo iniciar la aplicación. Recargue la página.'; });
