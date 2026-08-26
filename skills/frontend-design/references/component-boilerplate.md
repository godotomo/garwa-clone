# Component Boilerplate (GovTech & Public Sector Example)

## Accessibility-First Civic Public Portal Component (HTML + Tailwind CSS)

```html
<section class="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-8 shadow-sm transition-all duration-300" aria-labelledby="civic-portal-heading">
  <!-- Top Civic Status Notice -->
  <div class="mb-6 flex items-center justify-between rounded-lg bg-sky-50 px-4 py-3 border border-sky-200">
    <div class="flex items-center space-x-3">
      <span class="flex h-2.5 w-2.5 relative">
        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
        <span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-sky-600"></span>
      </span>
      <span class="text-xs font-semibold text-sky-900 tracking-wide uppercase">Layanan Portal Resmi Publik</span>
    </div>
    <span class="text-xs text-sky-700 font-medium">Aksesibilitas Standar WCAG AAA</span>
  </div>

  <div class="grid grid-cols-1 md:grid-cols-2 gap-8 items-center">
    <div>
      <h1 id="civic-portal-heading" class="text-3xl font-extrabold tracking-tight text-slate-900 sm:text-4xl">
        Layanan Administrasi Digital Warga
      </h1>
      <p class="mt-4 text-base leading-relaxed text-slate-600">
        Akses layanan perizinan, dokumen kependudukan, dan bantuan sosial secara transparan, aman, dan tanpa antrean fisik.
      </p>
      
      <!-- Action Buttons with Touch Targets (Google M3 Compliant) -->
      <div class="mt-6 flex flex-wrap gap-4">
        <button 
          type="button" 
          class="inline-flex h-12 min-w-[48px] items-center justify-center rounded-lg bg-sky-700 px-6 text-sm font-bold text-white shadow-md transition-all duration-150 hover:bg-sky-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-900 focus-visible:ring-offset-2 active:scale-95 disabled:opacity-50"
        >
          Ajukan Permohonan Layanan
        </button>
        <a 
          href="#panduan" 
          class="inline-flex h-12 min-w-[48px] items-center justify-center rounded-lg border border-slate-300 bg-white px-6 text-sm font-bold text-slate-700 transition-all duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-600 focus-visible:ring-offset-2 active:scale-95"
        >
          Panduan Syarat & Prosedur
        </a>
      </div>
    </div>

    <!-- Media Image with Unsplash Photo Protocol -->
    <div class="relative h-64 w-full overflow-hidden rounded-xl border border-slate-200 shadow-inner">
      <img 
        src="https://images.unsplash.com/photo-1541872703-74c5e44368f9?auto=format&fit=crop&w=800&q=80" 
        alt="Gedung Pelayanan Publik dan Layanan Pemerintah Digital" 
        width="800" 
        height="500"
        class="h-full w-full object-cover object-center"
        loading="eager"
      />
    </div>
  </div>
</section>
```
