// Create an axios-like api wrapper but with native fetch
const rawBaseUrl = (import.meta.env.VITE_API_URL || "").trim();
const BASE_URL = rawBaseUrl.endsWith("/") ? rawBaseUrl.slice(0, -1) : rawBaseUrl;

const buildUrl = (endpoint: string): string => {
    if (/^https?:\/\//i.test(endpoint)) return endpoint;
    return `${BASE_URL}${endpoint}`;
};

const getErrorMessage = async (response: Response): Promise<string> => {
    try {
        const body = await response.json();
        if (typeof body.detail === "string") return body.detail;
        if (Array.isArray(body.detail) && typeof body.detail[0]?.msg === "string") {
            return body.detail[0].msg.replace(/^Value error,\s*/i, "");
        }
    } catch {
        return "İstek tamamlanamadı.";
    }
    return "İstek tamamlanamadı.";
};

export const api = {
    get: async <T>(endpoint: string): Promise<T> => {
        const res = await fetch(buildUrl(endpoint));
        if (!res.ok) throw new Error(await getErrorMessage(res));
        return res.json();
    },
    post: async <T>(endpoint: string, data: any): Promise<T> => {
        const res = await fetch(buildUrl(endpoint), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        if (!res.ok) throw new Error(await getErrorMessage(res));
        return res.json();
    },
    put: async <T>(endpoint: string, data: any): Promise<T> => {
        const res = await fetch(buildUrl(endpoint), {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        if (!res.ok) throw new Error(await getErrorMessage(res));
        return res.json();
    },
    delete: async (endpoint: string): Promise<void> => {
        const res = await fetch(buildUrl(endpoint), {
            method: "DELETE",
        });
        if (!res.ok) throw new Error(await getErrorMessage(res));
    },
    patch: async <T>(endpoint: string, data?: any): Promise<T> => {
        const res = await fetch(buildUrl(endpoint), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: data ? JSON.stringify(data) : undefined,
        });
        if (!res.ok) throw new Error(await getErrorMessage(res));
        return res.json();
    },
};
