import { useCallback, useEffect, useRef, useState } from "react";
import {
    AlertCircle,
    ArrowDownRight,
    CheckCircle2,
    ChevronDown,
    Clock3,
    ExternalLink,
    LoaderCircle,
    Plus,
    RefreshCw,
    Save,
    Search,
    ShoppingBag,
    Trash2,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { tr } from "date-fns/locale";
import { toast } from "sonner";

import { api } from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

interface TrackedProduct {
    id: number;
    title: string;
    url: string;
    store_name: string;
    initial_price_cents: number;
    current_price_cents: number;
    initial_price: string;
    current_price: string;
    discount_percent: number;
    akakce_url: string;
    is_active: boolean;
    last_checked_at: string | null;
    last_error: string | null;
}

interface TrackingSettings {
    check_interval_minutes: number;
    last_check_completed_at: string | null;
}

const TRACKING_POLL_MS = 5000;

const parseApiDate = (value: string) => {
    const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
    return new Date(normalized);
};

const timeAgo = (value: string | null) => {
    if (!value) return "henüz yapılmadı";
    const parsed = parseApiDate(value);
    if (Number.isNaN(parsed.getTime())) return "bilinmiyor";
    return formatDistanceToNow(parsed, { addSuffix: true, locale: tr });
};

const errorMessage = (error: unknown, fallback: string) =>
    error instanceof Error && error.message ? error.message : fallback;

export function ProductTrackingPanel() {
    const [products, setProducts] = useState<TrackedProduct[]>([]);
    const [loading, setLoading] = useState(true);
    const [productUrl, setProductUrl] = useState("");
    const [addingProduct, setAddingProduct] = useState(false);
    const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);
    const [intervalMinutes, setIntervalMinutes] = useState("10");
    const [savingInterval, setSavingInterval] = useState(false);
    const [checkingProductId, setCheckingProductId] = useState<number | null>(null);
    const [mutatingProductId, setMutatingProductId] = useState<number | null>(null);
    const [confirmingDeleteProductId, setConfirmingDeleteProductId] = useState<number | null>(null);
    const [isListExpanded, setIsListExpanded] = useState(false);
    const lastCheckCompletedRef = useRef<string | null>(null);

    const fetchProducts = useCallback(async () => {
        try {
            setProducts(await api.get<TrackedProduct[]>("/dashboard/tracked-products"));
        } catch (error) {
            setFeedback({ type: "error", text: errorMessage(error, "Takip listesi yüklenemedi.") });
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        let cancelled = false;

        const bootstrap = async () => {
            try {
                const settings = await api.get<TrackingSettings>("/dashboard/tracked-products-settings");
                if (cancelled) return;
                setIntervalMinutes(String(settings.check_interval_minutes));
                lastCheckCompletedRef.current = settings.last_check_completed_at;
                await fetchProducts();
            } catch (error) {
                if (!cancelled) {
                    setLoading(false);
                    setFeedback({ type: "error", text: errorMessage(error, "Takip ayarları yüklenemedi.") });
                }
            }
        };

        const poll = async () => {
            try {
                const settings = await api.get<TrackingSettings>("/dashboard/tracked-products-settings");
                if (
                    settings.last_check_completed_at &&
                    lastCheckCompletedRef.current !== settings.last_check_completed_at
                ) {
                    lastCheckCompletedRef.current = settings.last_check_completed_at;
                    await fetchProducts();
                }
            } catch {
                return;
            }
        };

        void bootstrap();
        const timer = window.setInterval(() => void poll(), TRACKING_POLL_MS);
        return () => {
            cancelled = true;
            window.clearInterval(timer);
        };
    }, [fetchProducts]);

    const handleAddProduct = async (event: React.FormEvent) => {
        event.preventDefault();
        const url = productUrl.trim();
        if (!url) return;
        setAddingProduct(true);
        setFeedback(null);
        try {
            const product = await api.post<TrackedProduct>("/dashboard/tracked-products", { url });
            setProducts((current) => [product, ...current]);
            setIsListExpanded(true);
            setProductUrl("");
            setFeedback({ type: "success", text: "Ürün takibe alındı." });
        } catch (error) {
            setFeedback({ type: "error", text: errorMessage(error, "Ürün takibe alınamadı.") });
        } finally {
            setAddingProduct(false);
        }
    };

    const handleSaveInterval = async () => {
        const normalized = Math.max(1, Math.min(1440, Number(intervalMinutes) || 10));
        setSavingInterval(true);
        try {
            await api.put<TrackingSettings>("/dashboard/tracked-products-settings", {
                check_interval_minutes: normalized,
            });
            setIntervalMinutes(String(normalized));
            setFeedback({ type: "success", text: `Kontrol aralığı ${normalized} dakika olarak kaydedildi.` });
        } catch (error) {
            setFeedback({ type: "error", text: errorMessage(error, "Kontrol aralığı kaydedilemedi.") });
        } finally {
            setSavingInterval(false);
        }
    };

    const handleCheckProduct = async (productId: number) => {
        setCheckingProductId(productId);
        try {
            const updated = await api.post<TrackedProduct>(`/dashboard/tracked-products/${productId}/check`, {});
            setProducts((current) => current.map((product) => product.id === productId ? updated : product));
        } catch (error) {
            setFeedback({ type: "error", text: errorMessage(error, "Ürün fiyatı kontrol edilemedi.") });
        } finally {
            setCheckingProductId(null);
        }
    };

    const handleToggleProduct = async (productId: number) => {
        setMutatingProductId(productId);
        try {
            const updated = await api.patch<TrackedProduct>(`/dashboard/tracked-products/${productId}/toggle`);
            setProducts((current) => current.map((product) => product.id === productId ? updated : product));
        } catch (error) {
            setFeedback({ type: "error", text: errorMessage(error, "Takip durumu değiştirilemedi.") });
        } finally {
            setMutatingProductId(null);
        }
    };

    const handleDeleteProduct = async (productId: number) => {
        if (mutatingProductId === productId || confirmingDeleteProductId === productId) {
            return;
        }

        const toastId = `tracked-product-delete-${productId}`;
        const clearConfirm = () => setConfirmingDeleteProductId((current) => (current === productId ? null : current));

        const runDelete = async () => {
            setMutatingProductId(productId);
            try {
                await api.delete(`/dashboard/tracked-products/${productId}`);
                setProducts((current) => current.filter((product) => product.id !== productId));
                toast.dismiss(toastId);
                toast.success("Ürün takipten silindi.");
            } catch (error) {
                setFeedback({ type: "error", text: errorMessage(error, "Ürün silinemedi.") });
                toast.error(errorMessage(error, "Ürün silinemedi."));
            } finally {
                setMutatingProductId(null);
                clearConfirm();
            }
        };

        setConfirmingDeleteProductId(productId);
        toast.warning("Ürün takipten silinsin mi?", {
            id: toastId,
            description: "Bu işlem geri alınamaz.",
            action: {
                label: "Sil",
                onClick: () => {
                    void runDelete();
                },
            },
            cancel: {
                label: "Vazgeç",
                onClick: () => {
                    clearConfirm();
                    toast.dismiss(toastId);
                },
            },
            onDismiss: clearConfirm,
            duration: 7000,
        });
    };

    return (
        <section aria-labelledby="tracking-title" className="tracking-theme space-y-5">
            <div className="surface-panel flex flex-col justify-between gap-4 rounded-xl p-5 sm:flex-row sm:items-end">
                <div>
                    <p className="mb-2 text-xs font-bold uppercase tracking-[0.16em] text-cyan-700">Fiyat alarm ayarları</p>
                    <h1 id="tracking-title" className="hero-title section-hero-title text-[#102a43]">
                        Özel Ürün Takip
                    </h1>
                </div>
                <div className="inline-flex h-8 w-fit items-center gap-2 rounded-md border border-cyan-200 bg-cyan-50 px-2.5 text-[11px] font-semibold text-cyan-900">
                    <span className="h-2 w-2 rounded-full bg-cyan-500" />
                    {products.filter((product) => product.is_active).length} aktif takip
                </div>
            </div>

            <div className="surface-panel grid gap-3 rounded-lg p-4 lg:grid-cols-[minmax(0,1fr)_280px] lg:p-5">
                <form onSubmit={handleAddProduct} className="min-w-0 space-y-2">
                    <Label htmlFor="product-url" className="text-xs font-bold text-stone-700">Ürün bağlantısı</Label>
                    <div className="flex flex-col gap-2 sm:flex-row">
                        <Input
                            id="product-url"
                            type="url"
                            value={productUrl}
                            onChange={(event) => setProductUrl(event.target.value)}
                            placeholder="https://magaza.com/urun..."
                            required
                            className="h-11 min-w-0 border-cyan-100 bg-white/75 text-sm text-stone-900 placeholder:text-stone-400 focus-visible:ring-cyan-600"
                        />
                        <Button
                            type="submit"
                            disabled={addingProduct}
                            className="h-11 shrink-0 rounded-md bg-[#102a43] px-5 text-white hover:bg-[#1b3f63]"
                        >
                            {addingProduct ? <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
                            {addingProduct ? "İnceleniyor" : "Takibe al"}
                        </Button>
                    </div>
                </form>

                <div className="space-y-2 border-t border-cyan-100 pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
                    <Label htmlFor="tracking-interval" className="text-xs font-bold text-stone-700">Kontrol aralığı</Label>
                    <div className="flex items-center gap-2">
                        <div className="relative min-w-0 flex-1">
                            <Input
                                id="tracking-interval"
                                type="number"
                                min={1}
                                max={1440}
                                value={intervalMinutes}
                                onChange={(event) => setIntervalMinutes(event.target.value)}
                                className="h-11 border-cyan-100 bg-white/75 pr-12 text-sm text-stone-900 focus-visible:ring-cyan-600"
                            />
                            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold text-stone-500">dk</span>
                        </div>
                        <Button
                            type="button"
                            onClick={handleSaveInterval}
                            disabled={savingInterval}
                            title="Kontrol aralığını kaydet"
                            aria-label="Kontrol aralığını kaydet"
                            className="h-11 w-11 shrink-0 rounded-md bg-cyan-500 p-0 text-white hover:bg-cyan-400"
                        >
                            {savingInterval ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                        </Button>
                    </div>
                </div>
            </div>

            {feedback && (
                <div className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs font-semibold ${
                    feedback.type === "success"
                        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                        : "border-rose-200 bg-rose-50 text-rose-700"
                }`}>
                    {feedback.type === "success"
                        ? <CheckCircle2 className="h-4 w-4 shrink-0" />
                        : <AlertCircle className="h-4 w-4 shrink-0" />}
                    {feedback.text}
                </div>
            )}

            <div className="space-y-2">
                <button
                    type="button"
                    onClick={() => setIsListExpanded((current) => !current)}
                    className="flex w-full items-center justify-between rounded-md px-1 py-1 text-left"
                    aria-expanded={isListExpanded}
                    aria-controls="tracked-products-list"
                >
                    <h2 className="text-sm font-bold text-stone-900">Takip listesi</h2>
                    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-stone-500">
                        {products.length} ürün
                        <ChevronDown className={`h-4 w-4 transition-transform ${isListExpanded ? "rotate-180" : ""}`} />
                    </span>
                </button>

                {isListExpanded && (loading ? (
                    <div className="surface-panel flex h-28 items-center justify-center rounded-lg">
                        <LoaderCircle className="h-5 w-5 animate-spin text-emerald-700" />
                    </div>
                ) : products.length === 0 ? (
                    <div className="surface-panel flex h-32 flex-col items-center justify-center rounded-lg text-center">
                        <ShoppingBag className="mb-2 h-5 w-5 text-stone-400" />
                        <p className="text-sm font-semibold text-stone-700">Takip edilen ürün yok</p>
                    </div>
                ) : (
                    <div id="tracked-products-list" className="overflow-x-auto rounded-lg border border-stone-200 bg-white/90 dark:border-slate-700 dark:bg-slate-900/50">
                        <table className="w-full min-w-[1080px] border-collapse text-left">
                            <thead>
                                <tr className="border-b border-stone-200 bg-stone-100/80 text-[11px] uppercase tracking-[0.11em] text-stone-600 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
                                    <th className="px-3 py-2.5 font-semibold">Mağaza</th>
                                    <th className="px-3 py-2.5 font-semibold">Ürün</th>
                                    <th className="px-3 py-2.5 font-semibold">Güncel fiyat</th>
                                    <th className="px-3 py-2.5 font-semibold">Başlangıç</th>
                                    <th className="px-3 py-2.5 font-semibold">Değişim</th>
                                    <th className="px-3 py-2.5 font-semibold">Son kontrol</th>
                                    <th className="px-3 py-2.5 font-semibold">Durum</th>
                                    <th className="px-3 py-2.5 text-right font-semibold">İşlemler</th>
                                </tr>
                            </thead>
                            <tbody>
                                {products.map((product) => {
                                    const priceDropped = product.current_price_cents < product.initial_price_cents;
                                    const isMutating = mutatingProductId === product.id;
                                    return (
                                        <tr
                                            key={product.id}
                                            className={`border-b border-stone-200/80 transition hover:bg-stone-50/70 dark:border-slate-700 dark:hover:bg-slate-800/40 ${
                                                product.is_active ? "" : "opacity-60"
                                            }`}
                                        >
                                            <td className="px-3 py-3 align-middle">
                                                <span className="inline-flex rounded-md bg-stone-100 px-2 py-1 text-[10px] font-bold text-stone-600">
                                                    {product.store_name}
                                                </span>
                                            </td>
                                            <td className="max-w-[380px] px-3 py-3 align-middle">
                                                <a href={product.url} target="_blank" rel="noreferrer" className="line-clamp-2 text-sm font-bold leading-5 text-stone-900 transition hover:text-emerald-800">
                                                    {product.title}
                                                </a>
                                                {product.last_error && (
                                                    <span className="mt-1 inline-flex items-center gap-1 text-[10px] font-bold text-rose-700" title={product.last_error}>
                                                        <AlertCircle className="h-3 w-3" /> Kontrol hatası
                                                    </span>
                                                )}
                                            </td>
                                            <td className={`whitespace-nowrap px-3 py-3 text-sm font-extrabold align-middle ${priceDropped ? "text-emerald-700" : "text-stone-900"}`}>
                                                {product.current_price}
                                            </td>
                                            <td className="whitespace-nowrap px-3 py-3 text-xs font-semibold text-stone-600 align-middle">
                                                {product.initial_price}
                                            </td>
                                            <td className="px-3 py-3 align-middle">
                                                {priceDropped ? (
                                                    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-emerald-100 px-2 py-1 text-[10px] font-bold text-emerald-800">
                                                        <ArrowDownRight className="h-3 w-3" /> %{product.discount_percent}
                                                    </span>
                                                ) : (
                                                    <span className="text-xs font-semibold text-stone-400">-</span>
                                                )}
                                            </td>
                                            <td className="whitespace-nowrap px-3 py-3 text-xs text-stone-500 align-middle">
                                                <span className="inline-flex items-center gap-1">
                                                    <Clock3 className="h-3.5 w-3.5" /> {timeAgo(product.last_checked_at)}
                                                </span>
                                            </td>
                                            <td className="px-3 py-3 align-middle">
                                                <button
                                                    type="button"
                                                    role="switch"
                                                    aria-checked={product.is_active}
                                                    aria-label={product.is_active ? "Takibi duraklat" : "Takibi başlat"}
                                                    title={product.is_active ? "Takibi duraklat" : "Takibi başlat"}
                                                    onClick={() => handleToggleProduct(product.id)}
                                                    disabled={isMutating}
                                                    className={`relative h-6 w-11 rounded-full transition ${product.is_active ? "bg-emerald-600" : "bg-stone-300"}`}
                                                >
                                                    <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${product.is_active ? "translate-x-5" : "translate-x-0"}`} />
                                                </button>
                                            </td>
                                            <td className="px-3 py-3 align-middle">
                                                <div className="flex items-center justify-end gap-1">
                                                    <a
                                                        href={product.akakce_url}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        title="Akakçe'de ara"
                                                        aria-label="Akakçe'de ara"
                                                        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-2.5 text-[11px] font-bold text-amber-900 transition hover:bg-amber-100"
                                                    >
                                                        <Search className="h-3.5 w-3.5" /> Akakçe
                                                    </a>
                                                    <button type="button" onClick={() => handleCheckProduct(product.id)} disabled={checkingProductId === product.id} title="Şimdi kontrol et" aria-label="Şimdi kontrol et" className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-stone-200 text-stone-600 transition hover:border-emerald-300 hover:text-emerald-700 disabled:opacity-50">
                                                        <RefreshCw className={`h-4 w-4 ${checkingProductId === product.id ? "animate-spin" : ""}`} />
                                                    </button>
                                                    <a href={product.url} target="_blank" rel="noreferrer" title="Ürünü aç" aria-label="Ürünü aç" className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-stone-200 text-stone-600 transition hover:border-stone-400 hover:text-stone-900">
                                                        <ExternalLink className="h-4 w-4" />
                                                    </a>
                                                    <button type="button" onClick={() => handleDeleteProduct(product.id)} disabled={isMutating || confirmingDeleteProductId === product.id} title="Takipten sil" aria-label="Takipten sil" className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-stone-200 text-stone-500 transition hover:border-rose-300 hover:text-rose-600 disabled:opacity-50">
                                                        {isMutating ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                ))}
            </div>
        </section>
    );
}
