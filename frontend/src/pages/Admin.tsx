import { useState, useEffect } from "react";
import { api } from "../lib/api";
import { toast } from "sonner";
import { ProductTrackingPanel } from "../components/ProductTrackingPanel";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "../components/ui/dialog";
import { PlusCircle, Trash2, Globe, Clock3, MessageCircle, Tag, X, Power, Link2, Send, ShieldCheck, Radar } from "lucide-react";

interface TargetSite {
    id: number;
    name: string;
    url: string;
    source_type: string;
    topic_list_selector: string | null;
    title_selector: string | null;
    link_selector: string | null;
    date_selector: string | null;
    is_active: boolean;
}

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

type SourceType = "web" | "telegram";

const EMPTY_FORM = {
    name: "",
    url: "",
    source_type: "web" as SourceType,
    topic_list_selector: "",
    title_selector: "",
    link_selector: "",
    date_selector: "",
    is_active: true,
};

export function Admin() {
    const [sites, setSites] = useState<TargetSite[]>([]);
    const [showForm, setShowForm] = useState(false);
    const [formData, setFormData] = useState(EMPTY_FORM);
    const [menuOpen, setMenuOpen] = useState(false);
    const [selectedSite, setSelectedSite] = useState<TargetSite | null>(null);
    const [editFormData, setEditFormData] = useState(EMPTY_FORM);
    const [scrapeInterval, setScrapeInterval] = useState("1");
    const [keywords, setKeywords] = useState<KeywordFilter[]>([]);
    const [newKeyword, setNewKeyword] = useState("");
    const [manualTitle, setManualTitle] = useState("");
    const [manualUrl, setManualUrl] = useState("");
    const [manualSending, setManualSending] = useState(false);
    const [showManualForm, setShowManualForm] = useState(false);
    const [showKeywordForm, setShowKeywordForm] = useState(false);
    const [domains, setDomains] = useState<AllowedDomain[]>([]);
    const [newDomain, setNewDomain] = useState("");
    const [showDomainForm, setShowDomainForm] = useState(false);

    const fetchSites = async () => {
        const data = await api.get<TargetSite[]>("/admin/sites");
        setSites(data);
    };

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

    useEffect(() => {
        fetchSites();
        fetchSettings();
        fetchKeywords();
        fetchDomains();
    }, []);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        const payload: Record<string, unknown> = {
            name: formData.name,
            url: formData.url,
            source_type: formData.source_type,
            is_active: true,
            date_selector: formData.date_selector || null,
        };
        if (formData.source_type === "web") {
            payload.topic_list_selector = formData.topic_list_selector;
            payload.title_selector = formData.title_selector;
            payload.link_selector = formData.link_selector;
        }
        await api.post("/admin/sites", payload);
        setShowForm(false);
        setFormData(EMPTY_FORM);
        fetchSites();
    };

    const handleDelete = async (id: number) => {
        const runDelete = async () => {
            try {
                await api.delete(`/admin/sites/${id}`);
                await fetchSites();
                setMenuOpen(false);
                toast.success("Kaynak silindi.");
            } catch (error) {
                toast.error(error instanceof Error ? error.message : "Kaynak silinemedi.");
            }
        };

        toast.warning("Kaynak silinsin mi?", {
            description: "Bu işlem geri alınamaz.",
            action: {
                label: "Sil",
                onClick: () => {
                    void runDelete();
                },
            },
            cancel: {
                label: "Vazgeç",
                onClick: () => undefined,
            },
            duration: 10000,
        });
    };

    const openSiteMenu = (site: TargetSite) => {
        setSelectedSite(site);
        setEditFormData({
            name: site.name,
            url: site.url,
            source_type: (site.source_type || "web") as SourceType,
            topic_list_selector: site.topic_list_selector || "",
            title_selector: site.title_selector || "",
            link_selector: site.link_selector || "",
            date_selector: site.date_selector || "",
            is_active: site.is_active,
        });
        setMenuOpen(true);
    };

    const handleUpdate = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!selectedSite) return;

        const payload: Record<string, unknown> = {
            name: editFormData.name,
            url: editFormData.url,
            source_type: editFormData.source_type,
            is_active: editFormData.is_active,
            date_selector: editFormData.date_selector || null,
        };
        if (editFormData.source_type === "web") {
            payload.topic_list_selector = editFormData.topic_list_selector;
            payload.title_selector = editFormData.title_selector;
            payload.link_selector = editFormData.link_selector;
        }
        await api.put(`/admin/sites/${selectedSite.id}`, payload);
        await fetchSites();
        setMenuOpen(false);
    };

    const handleSaveInterval = async () => {
        const normalized = String(Math.max(1, Number(scrapeInterval) || 1));
        await api.put(`/admin/settings/scrape_interval_minutes`, {
            value: normalized,
            description: "Scrape interval in minutes",
        });
        setScrapeInterval(normalized);
    };

    const set = (key: keyof typeof EMPTY_FORM) => (e: React.ChangeEvent<HTMLInputElement>) =>
        setFormData({ ...formData, [key]: e.target.value });
    const setSourceType = (type: SourceType) => setFormData({ ...formData, source_type: type });

    const setEdit = (key: keyof typeof EMPTY_FORM) => (e: React.ChangeEvent<HTMLInputElement>) =>
        setEditFormData({ ...editFormData, [key]: e.target.value });
    const setEditSourceType = (type: SourceType) => setEditFormData({ ...editFormData, source_type: type });

    return (
        <div className="admin-theme space-y-8 animate-in fade-in duration-500">
            <ProductTrackingPanel />

            {/* Header */}
            <div className="surface-panel flex flex-col gap-3 rounded-xl p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center">
                    <Button
                        onClick={() => { setShowDomainForm(!showDomainForm); setShowKeywordForm(false); setShowForm(false); setShowManualForm(false); }}
                        className="h-9 w-full rounded-md bg-cyan-500 px-3 text-xs font-medium text-white hover:bg-cyan-400 sm:w-auto sm:px-4 sm:text-sm"
                    >
                        <ShieldCheck className="w-4 h-4 mr-1.5" />
                        Domainler
                    </Button>
                    <Button
                        onClick={() => { setShowKeywordForm(!showKeywordForm); setShowForm(false); setShowManualForm(false); setShowDomainForm(false); }}
                        className="h-9 w-full rounded-md bg-amber-500 px-3 text-xs font-medium text-white hover:bg-amber-400 sm:w-auto sm:px-4 sm:text-sm"
                    >
                        <Tag className="w-4 h-4 mr-1.5" />
                        Keywords
                    </Button>
                    <Button
                        onClick={() => { setShowManualForm(!showManualForm); setShowForm(false); setShowKeywordForm(false); setShowDomainForm(false); }}
                        className="h-9 w-full rounded-md bg-emerald-500 px-3 text-xs font-medium text-white hover:bg-emerald-400 sm:w-auto sm:px-4 sm:text-sm"
                    >
                        <Link2 className="w-4 h-4 mr-1.5" />
                        Link Oluştur
                    </Button>
                    <Button
                        onClick={() => { setShowForm(!showForm); setShowManualForm(false); setShowKeywordForm(false); setShowDomainForm(false); }}
                        className="h-9 w-full rounded-md bg-indigo-500 px-3 text-xs font-medium text-white hover:bg-indigo-400 sm:w-auto sm:px-4 sm:text-sm"
                    >
                        <PlusCircle className="w-4 h-4 mr-1.5" />
                        Kaynak Ekle
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
                        className="h-8 w-20 border-stone-300 bg-white px-2 text-center text-xs text-stone-900 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
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

            {/* Allowed Domains Form */}
            {showDomainForm && (
                <div className="surface-panel space-y-4 rounded-2xl p-6">
                    <p className="text-xs text-stone-500">Sadece bu domainlerden gelen fırsat linkleri Telegram'a gönderilir. Boşsa tüm linkler gönderilir.</p>
                    <form onSubmit={handleAddDomain} className="flex items-center gap-2">
                        <Input
                            placeholder="Ör: hepsiburada.com, trendyol.com"
                            value={newDomain}
                            onChange={(e) => setNewDomain(e.target.value)}
                            className="h-10 flex-1 border-stone-300 bg-stone-50 text-sm"
                        />
                        <Button
                            type="submit"
                            className="h-10 bg-cyan-500 px-4 text-white hover:bg-cyan-400 rounded-lg text-sm font-medium"
                        >
                            <PlusCircle className="w-4 h-4 mr-1.5" />
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
                                    <Power className="w-3 h-3" />
                                </button>
                                <span>{d.domain}</span>
                                <button
                                    type="button"
                                    onClick={() => handleDeleteDomain(d.id)}
                                    className="text-stone-400 transition hover:text-rose-600"
                                >
                                    <X className="w-3 h-3" />
                                </button>
                            </div>
                        ))}
                        {domains.length === 0 && (
                            <p className="text-xs text-stone-500">Henüz domain eklenmedi - tüm linkler gönderilecek.</p>
                        )}
                    </div>
                </div>
            )}

            {/* Keyword Filters Form */}
            {showKeywordForm && (
                <div className="surface-panel space-y-4 rounded-2xl p-6">
                    <p className="text-xs text-stone-500">Telegram kanallarından sadece bu keywordları içeren mesajlar alınır. Boşsa tüm mesajlar alınır.</p>
                    <form onSubmit={handleAddKeyword} className="flex items-center gap-2">
                        <Input
                            placeholder="Keyword girin (ör: mouse, ipad, kupon)"
                            value={newKeyword}
                            onChange={(e) => setNewKeyword(e.target.value)}
                            className="h-10 flex-1 border-stone-300 bg-stone-50 text-sm"
                        />
                        <Button
                            type="submit"
                            className="h-10 bg-amber-500 px-4 text-white hover:bg-amber-400 rounded-lg text-sm font-medium"
                        >
                            <PlusCircle className="w-4 h-4 mr-1.5" />
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
                                    <Power className="w-3 h-3" />
                                </button>
                                <span>{kw.keyword}</span>
                                <button
                                    type="button"
                                    onClick={() => handleDeleteKeyword(kw.id)}
                                    className="text-stone-400 transition hover:text-rose-600"
                                >
                                    <X className="w-3 h-3" />
                                </button>
                            </div>
                        ))}
                        {keywords.length === 0 && (
                            <p className="text-xs text-stone-500">Henüz keyword eklenmedi - tüm mesajlar alınacak.</p>
                        )}
                    </div>
                </div>
            )}

            {/* Manual Link Form */}
            {showManualForm && (
                <form
                    onSubmit={handleManualLink}
                    className="surface-panel space-y-5 rounded-2xl p-6"
                >
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
                            className="h-9 bg-emerald-500 hover:bg-emerald-400 text-white rounded-lg px-5 text-sm font-medium"
                        >
                            <Send className="w-4 h-4 mr-1.5" />
                            {manualSending ? "Gönderiliyor..." : "Oluştur & Gönder"}
                        </Button>
                    </div>
                </form>
            )}

            {/* Add Form */}
            {showForm && (
                <form
                    onSubmit={handleSubmit}
                    className="surface-panel space-y-5 rounded-2xl p-6"
                >
                    {/* Source Type Toggle */}
                    <div className="space-y-1.5">
                        <Label className="text-xs font-medium text-stone-600">Kaynak Türü</Label>
                        <div className="flex gap-2">
                            <button
                                type="button"
                                onClick={() => setSourceType("web")}
                                className={`flex items-center gap-2 h-9 rounded-full px-4 text-xs font-medium transition ${
                                    formData.source_type === "web"
                                        ? "bg-indigo-500 text-white"
                                        : "border border-stone-300 bg-stone-50 text-stone-700 hover:border-stone-400"
                                }`}
                            >
                                <Globe className="w-3.5 h-3.5" />
                                Web / Forum
                            </button>
                            <button
                                type="button"
                                onClick={() => setSourceType("telegram")}
                                className={`flex items-center gap-2 h-9 rounded-full px-4 text-xs font-medium transition ${
                                    formData.source_type === "telegram"
                                        ? "bg-sky-500 text-white"
                                        : "border border-stone-300 bg-stone-50 text-stone-700 hover:border-stone-400"
                                }`}
                            >
                                <MessageCircle className="w-3.5 h-3.5" />
                                Telegram Kanalı
                            </button>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-1.5">
                            <Label className="text-xs font-medium text-stone-600">
                                {formData.source_type === "telegram" ? "Kanal Adı" : "Site Adı"}
                            </Label>
                            <Input
                                placeholder={formData.source_type === "telegram" ? "Sıcak Fırsatlar" : "Donanim Arsivi"}
                                required
                                value={formData.name}
                                onChange={set("name")}
                                className="h-10 border-stone-300 bg-stone-50 text-sm"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-xs font-medium text-stone-600">
                                {formData.source_type === "telegram" ? "Kanal Kullanıcı Adı veya Linki" : "Hedef URL"}
                            </Label>
                            <Input
                                placeholder={formData.source_type === "telegram" ? "@kanaladi veya https://t.me/kanaladi" : "https://forum..."}
                                required
                                value={formData.url}
                                onChange={set("url")}
                                className="h-10 border-stone-300 bg-stone-50 text-sm"
                            />
                            {formData.source_type === "telegram" && (
                                <p className="text-[0.7rem] text-stone-500">Üye olduğunuz Telegram kanalının kullanıcı adı veya linki</p>
                            )}
                        </div>
                    </div>

                    {formData.source_type === "web" && (
                        <>
                            <div className="space-y-1.5">
                                <Label className="text-xs text-zinc-400 font-medium">Liste CSS Seçicisi</Label>
                                <Input placeholder=".structItem--thread" required value={formData.topic_list_selector} onChange={set("topic_list_selector")} className="h-10 border-stone-300 bg-stone-50 text-sm" />
                                <p className="text-[0.7rem] text-stone-500">Her bir konuyu temsil eden tekrarlanan HTML elementi</p>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div className="space-y-1.5">
                                    <Label className="text-xs font-medium text-stone-600">Başlık Seçicisi</Label>
                                    <Input placeholder=".structItem-title a" required value={formData.title_selector} onChange={set("title_selector")} className="h-10 border-stone-300 bg-stone-50 text-sm" />
                                </div>
                                <div className="space-y-1.5">
                                    <Label className="text-xs font-medium text-stone-600">Link Seçicisi</Label>
                                    <Input placeholder=".structItem-title a" required value={formData.link_selector} onChange={set("link_selector")} className="h-10 border-stone-300 bg-stone-50 text-sm" />
                                </div>
                            </div>

                            <div className="space-y-1.5">
                                <Label className="text-xs font-medium text-stone-600">Konu Oluşturma Tarihi Seçicisi (Opsiyonel)</Label>
                                <Input
                                    placeholder=".structItem-startDate time"
                                    value={formData.date_selector}
                                    onChange={set("date_selector")}
                                    className="h-10 border-stone-300 bg-stone-50 text-sm"
                                />
                                <p className="text-[0.7rem] text-stone-500">Son mesaj değil, konu açılış tarihini veren alan</p>
                            </div>
                        </>
                    )}

                    <div className="flex justify-end gap-3 pt-2">
                        <Button type="button" variant="ghost" onClick={() => setShowForm(false)} className="text-sm text-stone-500 hover:text-stone-800">
                            İptal
                        </Button>
                        <Button type="submit" className="bg-indigo-500 hover:bg-indigo-400 text-white rounded-lg h-9 px-5 text-sm font-medium">
                            Kaydet
                        </Button>
                    </div>
                </form>
            )}

            {/* Sites List */}
            <div className="space-y-3">
                {sites.map((site) => (
                    <div
                        key={site.id}
                        className="deal-card-pro flex min-w-0 items-center justify-between rounded-xl px-4 py-4 sm:px-5"
                        onClick={() => openSiteMenu(site)}
                    >
                        <div className="flex min-w-0 items-center gap-3 sm:gap-4">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#19382f]">
                                <Radar className="h-4 w-4 text-amber-300" />
                            </div>
                            <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                    <p className="text-sm font-medium text-stone-900">{site.name}</p>
                                    <span className={`text-[0.6rem] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded ${
                                        site.source_type === "telegram"
                                            ? "bg-sky-100 text-sky-700"
                                            : "bg-emerald-100 text-emerald-800"
                                    }`}>
                                        {site.source_type === "telegram" ? "Telegram" : "Web"}
                                    </span>
                                </div>
                                <p className="max-w-full truncate text-xs text-stone-500">{site.url}</p>
                            </div>
                        </div>
                        <div className="hidden items-center gap-3 md:flex">
                            {site.source_type === "web" && site.topic_list_selector && (
                                <code className="rounded bg-indigo-50 px-2 py-1 text-[0.7rem] text-indigo-700">
                                    {site.topic_list_selector}
                                </code>
                            )}
                        </div>
                    </div>
                ))}

                {sites.length === 0 && (
                    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-stone-300 bg-white/60 py-20">
                        <Globe className="mb-3 h-10 w-10 text-stone-400" />
                        <p className="text-sm text-stone-500">Henüz kaynak eklenmedi</p>
                    </div>
                )}
            </div>

            <Dialog open={menuOpen} onOpenChange={setMenuOpen}>
                <DialogContent className="surface-panel max-w-2xl border-stone-200 bg-white/90 text-stone-900">
                    <DialogHeader>
                        <DialogTitle>Kaynağı Düzenle</DialogTitle>
                        <DialogDescription className="text-stone-500">
                            Selector yanlışsa burada güncelleyip tekrar kaydedebilirsiniz.
                        </DialogDescription>
                    </DialogHeader>

                    <form onSubmit={handleUpdate} className="space-y-4">
                        {/* Source Type Toggle (read-only display in edit mode) */}
                        <div className="space-y-1.5">
                            <Label className="text-xs font-medium text-stone-600">Kaynak Türü</Label>
                            <div className="flex gap-2">
                                <button
                                    type="button"
                                    onClick={() => setEditSourceType("web")}
                                    className={`flex items-center gap-2 h-9 rounded-full px-4 text-xs font-medium transition ${
                                        editFormData.source_type === "web"
                                            ? "bg-indigo-500 text-white"
                                            : "border border-stone-300 bg-stone-50 text-stone-700 hover:border-stone-400"
                                    }`}
                                >
                                    <Globe className="w-3.5 h-3.5" />
                                    Web / Forum
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setEditSourceType("telegram")}
                                    className={`flex items-center gap-2 h-9 rounded-full px-4 text-xs font-medium transition ${
                                        editFormData.source_type === "telegram"
                                            ? "bg-sky-500 text-white"
                                            : "border border-stone-300 bg-stone-50 text-stone-700 hover:border-stone-400"
                                    }`}
                                >
                                    <MessageCircle className="w-3.5 h-3.5" />
                                    Telegram Kanalı
                                </button>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-1.5">
                                <Label className="text-xs font-medium text-stone-600">
                                    {editFormData.source_type === "telegram" ? "Kanal Adı" : "Site Adı"}
                                </Label>
                                <Input required value={editFormData.name} onChange={setEdit("name")} className="h-10 border-stone-300 bg-stone-50 text-sm" />
                            </div>
                            <div className="space-y-1.5">
                                <Label className="text-xs font-medium text-stone-600">
                                    {editFormData.source_type === "telegram" ? "Kanal Kullanıcı Adı veya Linki" : "Hedef URL"}
                                </Label>
                                <Input required value={editFormData.url} onChange={setEdit("url")} className="h-10 border-stone-300 bg-stone-50 text-sm" />
                            </div>
                        </div>

                        {editFormData.source_type === "web" && (
                            <>
                                <div className="space-y-1.5">
                                    <Label className="text-xs font-medium text-stone-600">Liste CSS Seçicisi</Label>
                                    <Input required value={editFormData.topic_list_selector} onChange={setEdit("topic_list_selector")} className="h-10 border-stone-300 bg-stone-50 text-sm" />
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    <div className="space-y-1.5">
                                        <Label className="text-xs font-medium text-stone-600">Başlık Seçicisi</Label>
                                        <Input required value={editFormData.title_selector} onChange={setEdit("title_selector")} className="h-10 border-stone-300 bg-stone-50 text-sm" />
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label className="text-xs font-medium text-stone-600">Link Seçicisi</Label>
                                        <Input required value={editFormData.link_selector} onChange={setEdit("link_selector")} className="h-10 border-stone-300 bg-stone-50 text-sm" />
                                    </div>
                                </div>

                                <div className="space-y-1.5">
                                    <Label className="text-xs font-medium text-stone-600">Konu Oluşturma Tarihi Seçicisi (Opsiyonel)</Label>
                                    <Input
                                        value={editFormData.date_selector}
                                        onChange={setEdit("date_selector")}
                                        className="h-10 border-stone-300 bg-stone-50 text-sm"
                                    />
                                </div>
                            </>
                        )}

                        <DialogFooter className="gap-2">
                            <Button
                                type="button"
                                variant="destructive"
                                onClick={() => selectedSite && handleDelete(selectedSite.id)}
                            >
                                <Trash2 className="w-4 h-4 mr-1.5" />
                                Sil
                            </Button>
                            <Button type="submit" className="bg-indigo-500 hover:bg-indigo-400 text-white">
                                Kaydet
                            </Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>
        </div>
    );
}
