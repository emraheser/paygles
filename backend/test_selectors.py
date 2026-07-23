from scrapling import Fetcher

URL = "https://forum.donanimarsivi.com/forumlar/Sicakfirsatlar/"


def main():
    try:
        print(f"Fetching {URL}")
        page = Fetcher.get(URL, timeout=20)

        title = page.css_first("title")
        print("Page title:", title.text if title else "no title")
        print("\nSearching for threads...")

        items = page.css('.structItem')
        print(f"Found {len(items)} .structItem elements")

        for item in items[:2]:
            print("\n--- ITEM ---")
            title_nodes = item.css('.structItem-title a')
            title_node = title_nodes[0] if title_nodes else None
            if title_node:
                print("Title:", title_node.text.strip())
                print("Link:", title_node.attrib.get('href'))
            else:
                print("No title node found using '.structItem-title a'")
                print("Content preview:", item.text[:100].strip())

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
