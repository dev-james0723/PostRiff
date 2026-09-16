package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/xpzouying/xiaohongshu-mcp/browser"
	"github.com/xpzouying/xiaohongshu-mcp/configs"
	"github.com/xpzouying/xiaohongshu-mcp/cookies"
	"github.com/xpzouying/xiaohongshu-mcp/xiaohongshu"
)

func main() {
	title := os.Getenv("EXPECTED_TITLE")
	if title == "" {
		log.Fatal("EXPECTED_TITLE is required")
	}
	if err := xiaohongshu.SetSite(xiaohongshu.SiteRednote); err != nil {
		log.Fatal(err)
	}
	configs.InitHeadless(true)
	configs.SetFingerprintSeed(configs.ResolveFingerprintSeed(cookies.NewLoadCookie(cookies.GetCookiesFilePathForSite(xiaohongshu.SiteRednote))))
	b := browser.NewBrowser(true, browser.WithFingerprintSeed(configs.FingerprintSeed()), browser.WithSite(xiaohongshu.SiteRednote))
	defer b.Close()
	page := b.NewPage()
	defer page.Close()
	if err := page.Navigate(xiaohongshu.Site().PublishURL); err != nil {
		log.Fatal(err)
	}
	if err := page.WaitLoad(); err != nil {
		log.Fatal(err)
	}
	time.Sleep(4 * time.Second)
	elems, err := page.Elements("*")
	if err != nil {
		log.Fatal(err)
	}
	clicked := false
	for _, elem := range elems {
		text, _ := elem.Text()
		if strings.TrimSpace(text) == "笔记管理" {
			meta, _ := elem.Eval(`() => ({tag:this.tagName, cls:this.className, href:this.getAttribute('href'), parentTag:this.parentElement?.tagName, parentClass:this.parentElement?.className, parentHref:this.parentElement?.getAttribute('href'), grandTag:this.parentElement?.parentElement?.tagName, grandClass:this.parentElement?.parentElement?.className, grandHref:this.parentElement?.parentElement?.getAttribute('href')})`)
			encoded, _ := json.Marshal(meta.Value)
			fmt.Printf("candidate=%s\n", encoded)
			if _, err := elem.Eval(`() => { let n=this; for(let i=0;i<4&&n;i++,n=n.parentElement){ if(n.tagName==='A' || n.onclick || n.getAttribute('role')==='button'){ n.click(); return true } } this.click(); return false }`); err != nil {
				log.Fatal(err)
			}
			clicked = true
			time.Sleep(2 * time.Second)
			info, _ := page.Info()
			if !strings.Contains(info.URL, "/publish/publish") {
				break
			}
		}
	}
	if !clicked {
		log.Fatal("note management control not found")
	}
	time.Sleep(5 * time.Second)
	info, _ := page.Info()
	body, _ := page.Element("body")
	text, _ := body.Text()
	lines := []string{}
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if strings.Contains(line, title) || strings.Contains(line, "仅自己可见") || strings.Contains(line, "定时") || strings.Contains(line, "已发布") {
			if len(line) > 300 {
				line = line[:300]
			}
			lines = append(lines, line)
		}
	}
	records := []map[string]any{}
	all, _ := page.Elements("*")
	for _, elem := range all {
		label, _ := elem.Text()
		if strings.TrimSpace(label) != title {
			continue
		}
		value, err := elem.Eval(`(wanted) => { let n=this; for(let i=0;i<9&&n;i++,n=n.parentElement){ const t=(n.innerText||'').trim(); if(t.includes(wanted) && t.includes('仅自己可见') && t.length<1200){ return {tag:n.tagName,cls:n.className,text:t} } } return null }`, title)
		if err == nil {
			raw, _ := json.Marshal(value.Value)
			item := map[string]any{}
			if json.Unmarshal(raw, &item) == nil {
				records = append(records, item)
			}
		}
	}
	summary := text
	if len(summary) > 2000 {
		summary = summary[:2000]
	}
	result := map[string]any{"url": info.URL, "matchingLines": lines, "titlePresent": strings.Contains(text, title), "selfOnlyPresent": strings.Contains(text, "仅自己可见"), "records": records, "pageTextPrefix": summary}
	out, _ := json.Marshal(result)
	fmt.Println(string(out))
}
