import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { api } from "../lib/api";
import { motion, AnimatePresence } from "framer-motion";
import { Bell, Clock, Flame, TrendingUp, Filter, ChevronDown, Send, Trash2, ShoppingBag } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { tr } from "date-fns/locale";
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

interface Topic {
    id: number;
    site_name: string;
    title: string;
    url: string;
    deal_url: string | null;
    clean_deal_url: string | null;
    deal_title: string | null;
    deal_price: string | null;
    notification_sent: boolean;
    domain_skipped: boolean;
    source_date: string | null;
    scraped_at: string;
}

interface SyncStatus {
    last_scrape_completed_at: string | null;
    scrape_interval_minutes: number;
}

const SYNC_STATUS_POLL_MS = 5000;

/** Play a short attention beep using Web Audio API — no external file needed. */
const playNotifSound = () => {
    try {
        const ctx = new AudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = "sine";
        // Two-tone chime: 880Hz then 1174Hz
        osc.frequency.setValueAtTime(880, ctx.currentTime);
        osc.frequency.setValueAtTime(1174, ctx.currentTime + 0.12);
        gain.gain.setValueAtTime(0.18, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.35);
    } catch {
        // AudioContext not available — silently skip.
    }
};

const parseApiDateToLocal = (value: string) => {
    // Backend returns naive UTC datetime strings; force UTC parsing.
    const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
    return new Date(normalized);
};

const getTopicDate = (topic: Topic) => parseApiDateToLocal(topic.source_date || topic.scraped_at);

const STORE_LABELS: Record<string, { label: string; color: string }> = {
    hepsiburada: { label: "Hepsiburada", color: "text-orange-300 bg-orange-400/10 border-orange-400/20" },
    trendyol: { label: "Trendyol", color: "text-orange-300 bg-orange-400/10 border-orange-400/20" },
    amazon: { label: "Amazon", color: "text-yellow-300 bg-yellow-400/10 border-yellow-400/20" },
    n11: { label: "N11", color: "text-purple-300 bg-purple-400/10 border-purple-400/20" },
    teknosa: { label: "Teknosa", color: "text-red-300 bg-red-400/10 border-red-400/20" },
    mediamarkt: { label: "MediaMarkt", color: "text-red-300 bg-red-400/10 border-red-400/20" },
    a101: { label: "A101", color: "text-blue-300 bg-blue-400/10 border-blue-400/20" },
    bim: { label: "BİM", color: "text-red-300 bg-red-400/10 border-red-400/20" },
    vatan: { label: "Vatan", color: "text-green-300 bg-green-400/10 border-green-400/20" },
    migros: { label: "Migros", color: "text-orange-300 bg-orange-400/10 border-orange-400/20" },
    gratis: { label: "Gratis", color: "text-pink-300 bg-pink-400/10 border-pink-400/20" },
    pttavm: { label: "PttAVM", color: "text-yellow-300 bg-yellow-400/10 border-yellow-400/20" },
    ciceksepeti: { label: "Çiçeksepeti", color: "text-pink-300 bg-pink-400/10 border-pink-400/20" },
    gittigidiyor: { label: "GittiGidiyor", color: "text-yellow-300 bg-yellow-400/10 border-yellow-400/20" },
    letgo: { label: "Letgo", color: "text-teal-300 bg-teal-400/10 border-teal-400/20" },
    aliexpress: { label: "AliExpress", color: "text-red-300 bg-red-400/10 border-red-400/20" },
    idefix: { label: "İdefix", color: "text-purple-300 bg-purple-400/10 border-purple-400/20" },
};

const getStoreBadge = (topic: Topic): { label: string; color: string } | null => {
    const url = topic.clean_deal_url || topic.deal_url;
    if (!url) return null;
    try {
        const hostname = new URL(url).hostname.toLowerCase();
        for (const [key, value] of Object.entries(STORE_LABELS)) {
            if (hostname.includes(key)) return value;
        }
    } catch { /* ignore invalid URLs */ }
    return null;
};

export function Dashboard() {
    const [topics, setTopics] = useState<Topic[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedSite, setSelectedSite] = useState("TUMU");
    const [showOlder, setShowOlder] = useState(false);
    const [sendingId, setSendingId] = useState<number | null>(null);
    const [deletingId, setDeletingId] = useState<number | null>(null);
    const [sendDialogOpen, setSendDialogOpen] = useState(false);
    const [sendTopic, setSendTopic] = useState<Topic | null>(null);
    const [sendTitle, setSendTitle] = useState("");
    const [sendLink, setSendLink] = useState("");
    const lastScrapeCompletedRef = useRef<string | null>(null);
    const knownTopicIdsRef = useRef<Set<number> | null>(null);
    const [notifPermission, setNotifPermission] = useState<NotificationPermission>(
        typeof Notification !== "undefined" ? Notification.permission : "denied"
    );

    const openSendDialog = (e: React.MouseEvent, topic: Topic) => {
        e.preventDefault();
        e.stopPropagation();
        setSendTopic(topic);
        setSendTitle(topic.deal_title || topic.title);
        setSendLink(topic.clean_deal_url || topic.deal_url || topic.url);
        setSendDialogOpen(true);
    };

    const handleForceSend = async () => {
        if (!sendTopic) {
            return;
        }
        setSendingId(sendTopic.id);
        try {
            await api.post(`/dashboard/topics/${sendTopic.id}/send`, {
                title: sendTitle,
                link: sendLink,
            });
            setTopics(prev => prev.map(t => t.id === sendTopic.id ? { ...t, notification_sent: true, domain_skipped: false } : t));
            setSendDialogOpen(false);
        } catch {
            alert("Gönderilemedi.");
        } finally {
            setSendingId(null);
        }
    };

    const handleDeleteTopic = async (e: React.MouseEvent, topicId: number) => {
        e.preventDefault();
        e.stopPropagation();
        if (!confirm("Bu kaydı silmek istediğine emin misin?")) {
            return;
        }
        setDeletingId(topicId);
        try {
            await api.delete(`/dashboard/topics/${topicId}`);
            setTopics(prev => prev.filter(t => t.id !== topicId));
        } catch {
            alert("Silinemedi.");
        } finally {
            setDeletingId(null);
        }
    };

    const requestNotifPermission = useCallback(async () => {
        if (typeof Notification === "undefined") return;
        if (Notification.permission === "default") {
            const result = await Notification.requestPermission();
            setNotifPermission(result);
        }
    }, []);

    const notifyNewTopics = useCallback((newTopics: Topic[]) => {
        // Always play sound regardless of Notification permission
        if (newTopics.length > 0) {
            playNotifSound();
        }
        if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
        for (const topic of newTopics) {
            const title = topic.deal_title || topic.title;
            const price = topic.deal_price ? ` — ${topic.deal_price} TL` : "";
            new Notification(`🔥 ${topic.site_name}`, {
                body: `${title}${price}`,
                icon: "/favicon.ico",
                tag: `topic-${topic.id}`,
            });
        }
    }, []);

    const fetchTopics = useCallback(async () => {
        try {
            const data = await api.get<Topic[]>("/dashboard/topics");
            // Detect genuinely new topics (not on first load)
            if (knownTopicIdsRef.current !== null) {
                const prev = knownTopicIdsRef.current;
                const brandNew = data.filter(t => !prev.has(t.id));
                if (brandNew.length > 0) {
                    notifyNewTopics(brandNew);
                }
            }
            knownTopicIdsRef.current = new Set(data.map(t => t.id));
            setTopics(data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, [notifyNewTopics]);

    const fetchSyncStatus = useCallback(async () => {
        try {
            const status = await api.get<SyncStatus>("/dashboard/sync-status");
            const lastCompletedAt = status.last_scrape_completed_at;
            if (!lastCompletedAt) {
                return;
            }
            if (!lastScrapeCompletedRef.current) {
                lastScrapeCompletedRef.current = lastCompletedAt;
                return;
            }
            if (lastScrapeCompletedRef.current !== lastCompletedAt) {
                lastScrapeCompletedRef.current = lastCompletedAt;
                await fetchTopics();
            }
        } catch (e) {
            console.error(e);
        }
    }, [fetchTopics]);

    useEffect(() => {
        let cancelled = false;

        const bootstrap = async () => {
            try {
                const status = await api.get<SyncStatus>("/dashboard/sync-status");
                if (!cancelled) {
                    lastScrapeCompletedRef.current = status.last_scrape_completed_at;
                }
            } catch (e) {
                console.error(e);
            } finally {
                if (!cancelled) {
                    await fetchTopics();
                }
            }
        };

        void requestNotifPermission();
        void bootstrap();
        const interval = setInterval(() => {
            void fetchSyncStatus();
        }, SYNC_STATUS_POLL_MS);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, [fetchTopics, fetchSyncStatus, requestNotifPermission]);

    const siteOptions = useMemo(() => {
        const unique = Array.from(new Set(topics.map((topic) => topic.site_name)));
        return ["TUMU", ...unique];
    }, [topics]);

    const visibleTopics = useMemo(() => {
        if (selectedSite === "TUMU") {
            return topics;
        }
        return topics.filter((topic) => topic.site_name === selectedSite);
    }, [topics, selectedSite]);

    const [recentTopics, olderTopics] = useMemo(() => {
        const now = Date.now();
        const oneHourMs = 1 * 60 * 60 * 1000;
        const recent: Topic[] = [];
        const older: Topic[] = [];

        for (const topic of visibleTopics) {
            const topicTime = parseApiDateToLocal(topic.source_date || topic.scraped_at).getTime();
            if (now - topicTime <= oneHourMs) {
                recent.push(topic);
            } else {
                older.push(topic);
            }
        }
        return [recent, older];
    }, [visibleTopics]);

    if (loading) {
        return (
            <div className="flex justify-center items-center h-[60vh]">
                <div className="flex flex-col items-center gap-4">
                    <div className="w-12 h-12 rounded-full border-[3px] border-indigo-500/30 border-t-indigo-500 animate-spin" />
                    <p className="text-sm text-zinc-400">Loading deals...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div>
                <h1 className="text-[1.6rem] font-bold tracking-tight text-zinc-100">
                    Hot Deals
                </h1>
            </div>

            <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-3 space-y-2.5">
                <div className="flex items-center gap-2 text-zinc-300 text-sm">
                    <Filter className="w-4 h-4 text-indigo-400" />
                    Kaynak Filtresi
                </div>
                <div className="flex flex-wrap gap-2">
                    {siteOptions.map((site) => (
                        <button
                            key={site}
                            type="button"
                            onClick={() => setSelectedSite(site)}
                            className={`h-8 rounded-full px-3 text-xs font-medium transition ${
                                selectedSite === site
                                    ? "bg-indigo-500 text-white"
                                    : "border border-zinc-700 bg-zinc-800 text-zinc-300 hover:border-zinc-600"
                            }`}
                        >
                            {site === "TUMU" ? "Tümü" : site}
                        </button>
                    ))}
                </div>
            </div>

            <div className="flex gap-3">
                <div className="flex items-center gap-2 bg-zinc-800/60 rounded-xl px-3 py-2 border border-zinc-700/50">
                    <TrendingUp className="w-4 h-4 text-indigo-400" />
                    <span className="text-xs text-zinc-300 font-medium">{visibleTopics.length} fırsat</span>
                </div>
                {notifPermission !== "granted" && typeof Notification !== "undefined" && (
                    <button
                        type="button"
                        onClick={requestNotifPermission}
                        className="flex items-center gap-2 bg-zinc-800/60 rounded-xl px-3 py-2 border border-zinc-700/50 hover:border-indigo-500/40 transition-all"
                    >
                        <Bell className="w-4 h-4 text-amber-400" />
                        <span className="text-xs text-zinc-300 font-medium">Bildirimleri Aç</span>
                    </button>
                )}
            </div>

            {/* Recent Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                <AnimatePresence>
                    {recentTopics.map((topic, index) => {
                        const topicDate = getTopicDate(topic);
                        const storeBadge = getStoreBadge(topic);
                        const isNotFoundTitle = (topic.deal_title || topic.title).toLowerCase().includes("sayfa bulunamad");
                        const showActions = !topic.notification_sent || topic.domain_skipped || isNotFoundTitle;
                        return (
                        <motion.a
                            key={topic.id}
                            href={topic.clean_deal_url || topic.deal_url || topic.url}
                            target="_blank"
                            rel="noreferrer"
                            initial={{ opacity: 0, y: 16 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: index * 0.04, duration: 0.35, ease: "easeOut" }}
                            className="group relative bg-zinc-900 rounded-2xl border border-zinc-800 p-4 hover:border-indigo-500/40 hover:bg-zinc-800/80 transition-all duration-300 cursor-pointer"
                        >
                            {/* Source badge + store badge + time */}
                            <div className="flex items-center justify-between mb-2.5">
                                <div className="flex items-center gap-2">
                                    <span className="inline-flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-wider text-amber-400 bg-amber-400/10 px-2.5 py-1 rounded-lg">
                                        <Flame className="w-3 h-3" />
                                        {topic.site_name}
                                    </span>
                                    {storeBadge && (
                                        <span className={`inline-flex items-center gap-1 text-[0.65rem] font-medium px-2 py-1 rounded-md border ${storeBadge.color}`}>
                                            <ShoppingBag className="w-3 h-3" />
                                            {storeBadge.label}
                                        </span>
                                    )}
                                    {(!topic.notification_sent || topic.domain_skipped) && (
                                        <span className="inline-flex items-center gap-1 text-[0.65rem] font-medium text-rose-300 bg-rose-400/10 px-2 py-1 rounded-md border border-rose-400/20">
                                            Gönderilmedi
                                        </span>
                                    )}
                                </div>
                                <span className="flex items-center gap-1 text-[0.7rem] text-zinc-500">
                                    <Clock className="w-3 h-3" />
                                    {formatDistanceToNow(topicDate, { addSuffix: true, locale: tr })}
                                </span>
                            </div>

                            {/* Title */}
                            <h3 className="text-[0.9rem] font-medium leading-snug text-zinc-200 group-hover:text-white transition-colors line-clamp-2">
                                {topic.deal_title || topic.title}
                            </h3>
                            {topic.deal_title && topic.deal_title !== topic.title && (
                                <p className="text-[0.7rem] text-zinc-500 mt-0.5 line-clamp-1">{topic.title}</p>
                            )}

                            <div className="mt-2 flex items-center justify-between gap-2">
                                {topic.deal_price ? (
                                    <span className="inline-flex items-center text-[0.7rem] font-semibold text-emerald-300 bg-emerald-500/10 px-2 py-1 rounded-md border border-emerald-500/20">
                                        {topic.deal_price}
                                    </span>
                                ) : (
                                    <span />
                                )}
                                {showActions && (
                                    <div className="flex justify-end gap-2">
                                        <button
                                            type="button"
                                            onClick={(e) => openSendDialog(e, topic)}
                                            disabled={sendingId === topic.id}
                                            className="inline-flex items-center gap-1 text-[0.65rem] font-medium text-indigo-300 hover:text-white bg-indigo-500/10 hover:bg-indigo-500/30 px-2 py-1 rounded-md border border-indigo-500/20 transition-all"
                                            title="Telegram'a gönder"
                                        >
                                            <Send className="w-3 h-3" />
                                            {sendingId === topic.id ? "..." : "Gönder"}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={(e) => handleDeleteTopic(e, topic.id)}
                                            disabled={deletingId === topic.id}
                                            className="inline-flex items-center gap-1 text-[0.65rem] font-medium text-rose-300 hover:text-white bg-rose-500/10 hover:bg-rose-500/30 px-2 py-1 rounded-md border border-rose-500/20 transition-all"
                                            title="Kaydı sil"
                                        >
                                            <Trash2 className="w-3 h-3" />
                                            {deletingId === topic.id ? "..." : "Sil"}
                                        </button>
                                    </div>
                                )}
                            </div>
                        </motion.a>
                        );
                    })}
                </AnimatePresence>
            </div>

            {olderTopics.length > 0 && (
                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-3 space-y-3">
                    <button
                        type="button"
                        onClick={() => setShowOlder((prev) => !prev)}
                        className="w-full flex items-center justify-between text-left"
                    >
                        <span className="text-sm text-zinc-300 font-medium">
                            1 saatten eski kayıtlar ({olderTopics.length})
                        </span>
                        <span className="inline-flex items-center gap-2 text-xs text-zinc-400">
                            {showOlder ? "Gizle" : "Göster"}
                            <ChevronDown className={`w-4 h-4 transition-transform ${showOlder ? "rotate-180" : ""}`} />
                        </span>
                    </button>

                    {showOlder && (
                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                            <AnimatePresence>
                                {olderTopics.map((topic, index) => {
                                    const topicDate = getTopicDate(topic);
                                    const storeBadge = getStoreBadge(topic);
                                    const isNotFoundTitle = (topic.deal_title || topic.title).toLowerCase().includes("sayfa bulunamad");
                                    const showActions = !topic.notification_sent || topic.domain_skipped || isNotFoundTitle;
                                    return (
                                    <motion.a
                                        key={topic.id}
                                        href={topic.clean_deal_url || topic.deal_url || topic.url}
                                        target="_blank"
                                        rel="noreferrer"
                                        initial={{ opacity: 0, y: 10 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        transition={{ delay: index * 0.02, duration: 0.2, ease: "easeOut" }}
                                        className="group relative bg-zinc-900 rounded-2xl border border-zinc-800 p-4 hover:border-indigo-500/40 hover:bg-zinc-800/80 transition-all duration-300 cursor-pointer"
                                    >
                                        <div className="flex items-center justify-between mb-2.5">
                                            <div className="flex items-center gap-2">
                                                <span className="inline-flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-wider text-amber-400 bg-amber-400/10 px-2.5 py-1 rounded-lg">
                                                    <Flame className="w-3 h-3" />
                                                    {topic.site_name}
                                                </span>
                                                {storeBadge && (
                                                    <span className={`inline-flex items-center gap-1 text-[0.65rem] font-medium px-2 py-1 rounded-md border ${storeBadge.color}`}>
                                                        <ShoppingBag className="w-3 h-3" />
                                                        {storeBadge.label}
                                                    </span>
                                                )}
                                                {(!topic.notification_sent || topic.domain_skipped) && (
                                                    <span className="inline-flex items-center gap-1 text-[0.65rem] font-medium text-rose-300 bg-rose-400/10 px-2 py-1 rounded-md border border-rose-400/20">
                                                        Gönderilmedi
                                                    </span>
                                                )}
                                            </div>
                                            <span className="flex items-center gap-1 text-[0.7rem] text-zinc-500">
                                                <Clock className="w-3 h-3" />
                                                {formatDistanceToNow(topicDate, { addSuffix: true, locale: tr })}
                                            </span>
                                        </div>
                                        <h3 className="text-[0.9rem] font-medium leading-snug text-zinc-200 group-hover:text-white transition-colors line-clamp-2">
                                            {topic.deal_title || topic.title}
                                        </h3>
                                        {topic.deal_title && topic.deal_title !== topic.title && (
                                            <p className="text-[0.7rem] text-zinc-500 mt-0.5 line-clamp-1">{topic.title}</p>
                                        )}

                                        <div className="mt-2 flex items-center justify-between gap-2">
                                            {topic.deal_price ? (
                                                <span className="inline-flex items-center text-[0.7rem] font-semibold text-emerald-300 bg-emerald-500/10 px-2 py-1 rounded-md border border-emerald-500/20">
                                                    {topic.deal_price}
                                                </span>
                                            ) : (
                                                <span />
                                            )}
                                            {showActions && (
                                                <div className="flex justify-end gap-2">
                                                    <button
                                                        type="button"
                                                        onClick={(e) => openSendDialog(e, topic)}
                                                        disabled={sendingId === topic.id}
                                                        className="inline-flex items-center gap-1 text-[0.65rem] font-medium text-indigo-300 hover:text-white bg-indigo-500/10 hover:bg-indigo-500/30 px-2 py-1 rounded-md border border-indigo-500/20 transition-all"
                                                        title="Telegram'a gönder"
                                                    >
                                                        <Send className="w-3 h-3" />
                                                        {sendingId === topic.id ? "..." : "Gönder"}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={(e) => handleDeleteTopic(e, topic.id)}
                                                        disabled={deletingId === topic.id}
                                                        className="inline-flex items-center gap-1 text-[0.65rem] font-medium text-rose-300 hover:text-white bg-rose-500/10 hover:bg-rose-500/30 px-2 py-1 rounded-md border border-rose-500/20 transition-all"
                                                        title="Kaydı sil"
                                                    >
                                                        <Trash2 className="w-3 h-3" />
                                                        {deletingId === topic.id ? "..." : "Sil"}
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    </motion.a>
                                    );
                                })}
                            </AnimatePresence>
                        </div>
                    )}
                </div>
            )}

            {visibleTopics.length === 0 && (
                <div className="col-span-full flex flex-col items-center justify-center py-24 bg-zinc-900/50 rounded-2xl border border-zinc-800">
                    <Flame className="w-10 h-10 text-zinc-600 mb-4" />
                    <p className="text-zinc-500 text-sm">Bu filtre için kayıt bulunamadı.</p>
                </div>
            )}

            {visibleTopics.length > 0 && recentTopics.length === 0 && (
                <div className="col-span-full flex flex-col items-center justify-center py-20 bg-zinc-900/50 rounded-2xl border border-zinc-800">
                        <Flame className="w-10 h-10 text-zinc-600 mb-4" />
                        <p className="text-zinc-500 text-sm">Son 1 saatte yeni kayıt yok. Eski kayıtları aşağıdan açabilirsin.</p>
                </div>
            )}

            <Dialog open={sendDialogOpen} onOpenChange={setSendDialogOpen}>
                <DialogContent className="border-zinc-800 bg-zinc-900 text-zinc-100 sm:max-w-md">
                    <DialogHeader>
                        <DialogTitle>Telegram'a Gönder</DialogTitle>
                        <DialogDescription className="text-zinc-400">
                            Başlık ve link otomatik geldi. Göndermeden önce düzenleyebilirsin.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                        <div className="space-y-1.5">
                            <Label htmlFor="send-title">Başlık</Label>
                            <Input
                                id="send-title"
                                value={sendTitle}
                                onChange={(e) => setSendTitle(e.target.value)}
                                placeholder="Başlık"
                                className="border-zinc-700 bg-zinc-950"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="send-link">Link</Label>
                            <Input
                                id="send-link"
                                value={sendLink}
                                onChange={(e) => setSendLink(e.target.value)}
                                placeholder="https://..."
                                className="border-zinc-700 bg-zinc-950"
                            />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setSendDialogOpen(false)}>
                            Vazgeç
                        </Button>
                        <Button onClick={handleForceSend} disabled={!sendTopic || sendingId === sendTopic.id}>
                            {sendTopic && sendingId === sendTopic.id ? "Gönderiliyor..." : "Gönder"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
