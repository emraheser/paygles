import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
    Clock3,
    Link2,
    PlusCircle,
    Power,
    Send,
    ShieldCheck,
    Tag,
    X,
} from "lucide-react";

import { api } from "../lib/api";
import { ProductTrackingPanel } from "../components/ProductTrackingPanel";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

interface AppSetting {
    key: string;
    value: string;
    description: string | null;
}

interface KeywordFilter {
    id: number;
    keyword: string;
    is_active: boolean;
    created_at: string;
}

interface AllowedDomain {
    id: number;
    domain: string;
    is_active: boolean;
    created_at: string;
}

export function Admin() {
    const [scrapeInterval, setScrapeInterval] = useState("1");

    const [keywords, setKeywords] = useState<KeywordFilter[]>([]);
    const [newKeyword, setNewKeyword] = useState("");
    const [showKeywordForm, setShowKeywordForm] = useState(false);

    const [domains, setDomains] = useState<AllowedDomain[]>([]);
    const [newDomain, setNewDomain] = useState("");
    const [showDomainForm, setShowDomainForm] = useState(false);

    const [manualTitle, setManualTitle] = useState("");
    const [manualUrl, setManualUrl] = useState("");
    const [manualSending, setManualSending] = useState(false);
    const [showManualForm, setShowManualForm] = useState(false);

    const fetchSettings = async () => {
        const settings = await api.get<AppSetting[]>("/admin/settings");
        const intervalSetting = settings.find((s) => s.key === "scrape_interval_minutes");
        if (intervalSetting?.value) {
            setScrapeInterval(intervalSetting.value);
        }
    };

    const fetchKeywords = async () => {
        const data = await api.get<KeywordFilter[]>("/admin/keywords");
        setKeywords(data);
    };

    const fetchDomains = async () => {
        const data = await api.get<AllowedDomain[]>("/admin/domains");
        setDomains(data);
    };

    useEffect(() => {
        fetchSettings();
        fetchKeywords();
        fetchDomains();
    }, []);

    const handleSaveInterval = async () => {
        const normalized = String(Math.max(1, Number(scrapeInterval) || 1));
        await api.put("/admin/settings/scrape_interval_minutes", {
            value: normalized,
            description: "Scrape interval in minutes",
        });
        setScrapeInterval(normalized);
    };

    const handleAddDomain = async (e: React.FormEvent) => {
        e.preventDefault();
        const trimmed = newDomain.trim();
        if (!trimmed) return;
        await api.post("/admin/domains", { domain: trimmed });
        setNewDomain("");
        fetchDomains();
    };

    const handleDeleteDomain = async (id: number) => {
        await api.delete(`/admin/domains/${id}`);
        fetchDomains();
    };

    const handleToggleDomain = async (id: number) => {
        await api.patch(`/admin/domains/${id}/toggle`);
        fetchDomains();
    };

    const handleAddKeyword = async (e: React.FormEvent) => {
        e.preventDefault();
        const trimmed = newKeyword.trim();
        if (!trimmed) return;
        await api.post("/admin/keywords", { keyword: trimmed });
        setNewKeyword("");
        fetchKeywords();
    };

    const handleDeleteKeyword = async (id: number) => {
        await api.delete(`/admin/keywords/${id}`);
        fetchKeywords();
    };

    const handleToggleKeyword = async (id: number) => {
        await api.patch(`/admin/keywords/${id}/toggle`);
        fetchKeywords();
    };

    const handleManualLink = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!manualTitle.trim() || !manualUrl.trim()) return;
        setManualSending(true);
        try {
            await api.post("/admin/manual-link", {
                title: manualTitle.trim(),
                deal_url: manualUrl.trim(),
            });
            setManualTitle("");
            setManualUrl("");
            toast.success("Link oluşturuldu, bildirim gönderilecek.");
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "Hata oluştu.");
        } finally {
            setManualSending(false);
        }
    };

    return (
        <div className="admin-theme space-y-8 animate-in fade-in duration-500">
            <ProductTrackingPanel />

            <div className="surface-panel flex flex-col gap-3 rounded-xl p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="grid grid-cols-1 gap-2 sm:flex sm:items-center">
                    <Button
                        onClick={() => {
                            setShowDomainForm(!showDomainForm);
                            setShowKeywordForm(false);
                            setShowManualForm(false);
                        }}
                        className="h-9 w-full rounded-md bg-cyan-500 px-3 text-xs font-medium text-white hover:bg-cyan-400 sm:w-auto sm:px-4 sm:text-sm"
                    >
                        <ShieldCheck className="mr-1.5 h-4 w-4" />
                        Domainler
                    </Button>
                    <Button
                        onClick={() => {
                            setShowKeywordForm(!showKeywordForm);
                            setShowManualForm(false);
                            setShowDomainForm(false);
                        }}
                        className="h-9 w-full rounded-md bg-amber-500 px-3 text-xs font-medium text-white hover:bg-amber-400 sm:w-auto sm:px-4 sm:text-sm"
                    >
                        <Tag className="mr-1.5 h-4 w-4" />
                        Keywords
                    </Button>
                    <Button
                        onClick={() => {
                            setShowManualForm(!showManualForm);
                            setShowKeywordForm(false);
                            setShowDomainForm(false);
                        }}
                        className="h-9 w-full rounded-md bg-emerald-500 px-3 text-xs font-medium text-white hover:bg-emerald-400 sm:w-auto sm:px-4 sm:text-sm"
                    >
                        <Link2 className="mr-1.5 h-4 w-4" />
                        Link Oluştur
                    </Button>
                </div>
                <div className="flex w-full items-center justify-end gap-1.5 sm:w-auto">
                    <Clock3 className="h-4 w-4 shrink-0 text-emerald-700" />
                    <Input
                        type="number"
                        min={1}
                        max={99999}
                        value={scrapeInterval}
                        onChange={(e) => setScrapeInterval(e.target.value)}
                        className="h-8 w-20 border-stone-300 bg-white px-2 text-center text-xs text-stone-900 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                    />
                    <span className="text-xs text-stone-500">dk</span>
                    <Button
                        type="button"
                        onClick={handleSaveInterval}
                        className="h-8 rounded-md bg-indigo-500 px-3 text-xs text-white hover:bg-indigo-400"
                    >
                        Uygula
                    </Button>
                </div>
            </div>

            {showDomainForm && (
                <div className="surface-panel space-y-4 rounded-2xl p-6">
                    <p className="text-xs text-stone-500">
                        Sadece bu domainlerden gelen fırsat linkleri Telegram'a gönderilir. Boşsa tüm linkler gönderilir.
                    </p>
                    <form onSubmit={handleAddDomain} className="flex items-center gap-2">
                        <Input
                            placeholder="Ör: hepsiburada.com, trendyol.com"
                            value={newDomain}
                            onChange={(e) => setNewDomain(e.target.value)}
                            className="h-10 flex-1 border-stone-300 bg-stone-50 text-sm"
                        />
                        <Button
                            type="submit"
                            className="h-10 rounded-lg bg-cyan-500 px-4 text-sm font-medium text-white hover:bg-cyan-400"
                        >
                            <PlusCircle className="mr-1.5 h-4 w-4" />
                            Ekle
                        </Button>
                    </form>
                    <div className="flex flex-wrap gap-2">
                        {domains.map((d) => (
                            <div
                                key={d.id}
                                className={`group flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                                    d.is_active
                                        ? "border-cyan-400/40 bg-cyan-50 text-cyan-700"
                                        : "border-stone-300 bg-stone-100 text-stone-400 line-through"
                                }`}
                            >
                                <button
                                    type="button"
                                    onClick={() => handleToggleDomain(d.id)}
                                    title={d.is_active ? "Devre dışı bırak" : "Aktif et"}
                                    className="transition hover:text-stone-900"
                                >
                                    <Power className="h-3 w-3" />
                                </button>
                                <span>{d.domain}</span>
                                <button
                                    type="button"
                                    onClick={() => handleDeleteDomain(d.id)}
                                    className="text-stone-400 transition hover:text-rose-600"
                                >
                                    <X className="h-3 w-3" />
                                </button>
                            </div>
                        ))}
                        {domains.length === 0 && (
                            <p className="text-xs text-stone-500">Henüz domain eklenmedi - tüm linkler gönderilecek.</p>
                        )}
                    </div>
                </div>
            )}

            {showKeywordForm && (
                <div className="surface-panel space-y-4 rounded-2xl p-6">
                    <p className="text-xs text-stone-500">
                        Telegram kanalları ve Donanım Arşivi kaynağında sadece bu keywordları içeren içerikler alınır. Boşsa tüm içerikler alınır.
                    </p>
                    <form onSubmit={handleAddKeyword} className="flex items-center gap-2">
                        <Input
                            placeholder="Keyword girin (ör: mouse, ipad, kupon)"
                            value={newKeyword}
                            onChange={(e) => setNewKeyword(e.target.value)}
                            className="h-10 flex-1 border-stone-300 bg-stone-50 text-sm"
                        />
                        <Button
                            type="submit"
                            className="h-10 rounded-lg bg-amber-500 px-4 text-sm font-medium text-white hover:bg-amber-400"
                        >
                            <PlusCircle className="mr-1.5 h-4 w-4" />
                            Ekle
                        </Button>
                    </form>
                    <div className="flex flex-wrap gap-2">
                        {keywords.map((kw) => (
                            <div
                                key={kw.id}
                                className={`group flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                                    kw.is_active
                                        ? "border-amber-400/50 bg-amber-50 text-amber-700"
                                        : "border-stone-300 bg-stone-100 text-stone-400 line-through"
                                }`}
                            >
                                <button
                                    type="button"
                                    onClick={() => handleToggleKeyword(kw.id)}
                                    title={kw.is_active ? "Devre dışı bırak" : "Aktif et"}
                                    className="transition hover:text-stone-900"
                                >
                                    <Power className="h-3 w-3" />
                                </button>
                                <span>{kw.keyword}</span>
                                <button
                                    type="button"
                                    onClick={() => handleDeleteKeyword(kw.id)}
                                    className="text-stone-400 transition hover:text-rose-600"
                                >
                                    <X className="h-3 w-3" />
                                </button>
                            </div>
                        ))}
                        {keywords.length === 0 && (
                            <p className="text-xs text-stone-500">Henüz keyword eklenmedi - tüm mesajlar alınacak.</p>
                        )}
                    </div>
                </div>
            )}

            {showManualForm && (
                <form onSubmit={handleManualLink} className="surface-panel space-y-5 rounded-2xl p-6">
                    <div className="space-y-1.5">
                        <Label className="text-xs font-medium text-stone-600">Başlık</Label>
                        <Input
                            placeholder="Örn: iPhone 15 Pro Max %40 indirim"
                            required
                            value={manualTitle}
                            onChange={(e) => setManualTitle(e.target.value)}
                            className="h-10 border-stone-300 bg-stone-50 text-sm"
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label className="text-xs font-medium text-stone-600">Fırsat Linki</Label>
                        <Input
                            placeholder="https://..."
                            required
                            type="url"
                            value={manualUrl}
                            onChange={(e) => setManualUrl(e.target.value)}
                            className="h-10 border-stone-300 bg-stone-50 text-sm"
                        />
                    </div>
                    <div className="flex justify-end">
                        <Button
                            type="submit"
                            disabled={manualSending}
                            className="h-9 rounded-lg bg-emerald-500 px-5 text-sm font-medium text-white hover:bg-emerald-400"
                        >
                            <Send className="mr-1.5 h-4 w-4" />
                            {manualSending ? "Gönderiliyor..." : "Oluştur & Gönder"}
                        </Button>
                    </div>
                </form>
            )}

        </div>
    );
}
