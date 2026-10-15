import { Component, ElementRef, ViewChild, computed, inject, signal } from '@angular/core';
import { CommonModule, registerLocaleData } from '@angular/common';
import localeEs from '@angular/common/locales/es';
import { FormsModule, NgForm } from '@angular/forms';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom, timeout } from 'rxjs';

registerLocaleData(localeEs);
// URL base de la API, sin barra final. Ejemplo: 'http://mi-alb-123.us-east-1.elb.amazonaws.com'.
// Vacía = mismo origen (proxy de ng serve o CloudFront con /api/*).
const API_BASE = '';
interface Producto { id: string; nombre: string; precio: string | number; stock: number; creado_en: string; }
interface Info { motor: string; servidor: string; instance_id: string | null; zona_disponibilidad: string | null; base_datos_disponible: boolean; }

@Component({selector: 'app-root', standalone: true, imports: [CommonModule, FormsModule], templateUrl: './app.html'})
export class App {
  private http = inject(HttpClient);
  @ViewChild('editor') editor!: ElementRef<HTMLDialogElement>;
  @ViewChild('confirmacion') confirmacion!: ElementRef<HTMLDialogElement>;
  productos = signal<Producto[]>([]);
  info = signal<Info | null>(null);
  cargando = signal(false);
  guardando = signal(false);
  falloCarga = signal(false);
  aviso = signal<{texto: string; error: boolean} | null>(null);
  busqueda = signal('');
  oscuro = signal(false);
  seleccion: Producto | null = null;
  pendiente: Producto | null = null;
  datos = {nombre: '', precio: 0 as number | null, stock: 0 as number | null};
  filtrados = computed(() => this.productos().filter(p => p.nombre.toLocaleLowerCase('es').includes(this.busqueda().toLocaleLowerCase('es'))));
  unidades = computed(() => this.productos().reduce((total, p) => total + p.stock, 0));
  valor = computed(() => this.productos().reduce((total, p) => total + Math.round(Number(p.precio) * 100) * p.stock, 0) / 100);
  private temporizador?: ReturnType<typeof setTimeout>;

  constructor() {
    try { this.oscuro.set(localStorage.getItem('tema') === 'dark'); } catch { /* El tema funciona sin almacenamiento. */ }
    this.aplicarTema();
    void this.cargar();
  }

  cambiarTema() {
    this.oscuro.update(v => !v);
    this.aplicarTema();
    try { localStorage.setItem('tema', this.oscuro() ? 'dark' : 'light'); } catch { /* Preferencia válida para esta sesión. */ }
  }
  private aplicarTema() { document.documentElement.dataset['theme'] = this.oscuro() ? 'dark' : 'light'; }
  notificar(texto: string, error = false) {
    clearTimeout(this.temporizador);
    this.aviso.set({texto, error});
    this.temporizador = setTimeout(() => this.aviso.set(null), 7000);
  }
  private mensaje(error: unknown) {
    return error instanceof HttpErrorResponse && error.error?.detalle
      ? String(error.error.detalle) : 'La API no responde. Revise la conexión e intente nuevamente.';
  }
  async cargar() {
    if (this.cargando()) return;
    this.cargando.set(true);
    const resultados = await Promise.allSettled([
      firstValueFrom(this.http.get<Producto[]>(API_BASE + '/api/productos').pipe(timeout(20000))),
      firstValueFrom(this.http.get<Info>(API_BASE + '/api/info').pipe(timeout(20000)))
    ]);
    const [productos, info] = resultados;
    if (productos.status === 'fulfilled') {
      this.productos.set(productos.value); this.falloCarga.set(false);
    } else { this.falloCarga.set(true); this.notificar(this.mensaje(productos.reason), true); }
    if (info.status === 'fulfilled') {
      this.info.set(info.value);
      if (!info.value.base_datos_disponible) this.notificar('El servidor responde, pero la base de datos no está disponible.', true);
    } else { this.info.set(null); this.notificar('No se pudo consultar la información del servidor.', true); }
    this.cargando.set(false);
  }
  abrir(producto: Producto | null, formulario: NgForm) {
    this.seleccion = producto;
    this.datos = producto ? {nombre: producto.nombre, precio: Number(producto.precio), stock: producto.stock} : {nombre: '', precio: 0, stock: 0};
    formulario.resetForm(this.datos);
    this.editor.nativeElement.showModal();
  }
  cerrarEditor() { if (!this.guardando()) this.editor.nativeElement.close(); }
  precioValido() {
    const p = this.datos.precio;
    return p !== null && Number.isFinite(p) && p >= 0 && p <= 9999999999.99 && Math.abs(p * 100 - Math.round(p * 100)) < 0.0001;
  }
  stockValido() { return this.datos.stock !== null && Number.isInteger(this.datos.stock) && this.datos.stock >= 0 && this.datos.stock <= 2147483647; }
  async guardar(formulario: NgForm) {
    if (formulario.invalid || !this.datos.nombre.trim() || !this.precioValido() || !this.stockValido() || this.guardando()) return;
    this.guardando.set(true);
    try {
      const datos = {...this.datos, nombre: this.datos.nombre.trim()};
      const peticion = this.seleccion ? this.http.put<Producto>(API_BASE + '/api/productos/' + this.seleccion.id, datos) : this.http.post<Producto>(API_BASE + '/api/productos', datos);
      const producto = await firstValueFrom(peticion.pipe(timeout(20000)));
      this.productos.update(lista => this.seleccion ? lista.map(p => p.id === producto.id ? producto : p) : [producto, ...lista]);
      this.editor.nativeElement.close();
      this.notificar(this.seleccion ? 'Producto actualizado.' : 'Producto creado.');
    } catch (error) { this.notificar(this.mensaje(error), true); }
    finally { this.guardando.set(false); }
  }
  pedirEliminar(producto: Producto) { this.pendiente = producto; this.confirmacion.nativeElement.showModal(); }
  async eliminar() {
    if (!this.pendiente || this.guardando()) return;
    this.guardando.set(true);
    try {
      await firstValueFrom(this.http.delete(API_BASE + '/api/productos/' + this.pendiente.id).pipe(timeout(20000)));
      this.productos.update(lista => lista.filter(p => p.id !== this.pendiente?.id));
      this.confirmacion.nativeElement.close();
      this.notificar('Producto eliminado.');
    } catch (error) { this.notificar(this.mensaje(error), true); }
    finally { this.guardando.set(false); }
  }
}
