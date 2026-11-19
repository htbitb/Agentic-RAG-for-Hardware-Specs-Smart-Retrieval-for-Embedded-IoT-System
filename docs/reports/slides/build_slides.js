
const pptxgen = require("pptxgenjs");
const path = require("path");
const C9 = process.env.C9_JSON ? JSON.parse(process.env.C9_JSON) : null;
const pres = new pptxgen(); pres.layout = "LAYOUT_16x9";
pres.title = "Agentic RAG for Hardware Specs - Vòng 1"; pres.author = "Nhóm CO5151";
const INK="0B3C3A", PAPER="FFFFFF", MIST="EAF2EF", COPPER="C8803A", SLATE="43524F", SOFT="9FB8B2";
const HF="Cambria", BF="Calibri";
function title(s, text){ s.addText(text,{x:0.5,y:0.3,w:9,h:0.8,fontFace:HF,fontSize:32,bold:true,color:INK,margin:0,isTextBox:true,valign:"middle"}); }
function foot(s,n){ s.addText("CO5151 · Agentic RAG for Hardware Specs · vòng 1",{x:0.5,y:5.28,w:7,h:0.25,fontFace:BF,fontSize:10,color:"6B7C78",margin:0,isTextBox:true}); s.addText(String(n),{x:9.0,y:5.28,w:0.5,h:0.25,fontFace:BF,fontSize:10,color:"6B7C78",align:"right",margin:0,isTextBox:true}); }
function card(s,x,y,w,h,head,body,fill){ s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x,y,w,h,fill:{color:fill||MIST},line:{color:fill||MIST},rectRadius:0.08}); s.addText(head,{x:x+0.2,y:y+0.12,w:w-0.4,h:0.4,fontFace:HF,fontSize:16,bold:true,color:INK,margin:0,isTextBox:true}); s.addText(body,{x:x+0.2,y:y+0.55,w:w-0.4,h:h-0.65,fontFace:BF,fontSize:13,color:SLATE,margin:0,isTextBox:true,valign:"top"}); }
function stat(s,x,y,w,big,label,color){ s.addText(big,{x,y,w,h:0.9,fontFace:HF,fontSize:44,bold:true,color:color||COPPER,margin:0,isTextBox:true,valign:"middle"}); s.addText(label,{x,y:y+0.9,w,h:0.6,fontFace:BF,fontSize:13,color:SLATE,margin:0,isTextBox:true,valign:"top"}); }
let n=0;
// 1 title
{ const s=pres.addSlide(); s.background={color:INK}; n++;
  s.addText("Agentic RAG for Hardware Specs",{x:0.7,y:1.3,w:8.6,h:1.0,fontFace:HF,fontSize:40,bold:true,color:"FFFFFF",margin:0,isTextBox:true});
  s.addText("Agent thiết kế phần cứng nhúng có kiểm chứng, phân quyền và đo được",{x:0.7,y:2.4,w:8.2,h:0.9,fontFace:BF,fontSize:20,color:"CFE3DD",margin:0,isTextBox:true});
  s.addText("STM32G474 · ESP32 · nRF52840 · FreeRTOS",{x:0.7,y:3.4,w:8,h:0.4,fontFace:BF,fontSize:16,color:COPPER,bold:true,margin:0,isTextBox:true});
  s.addText("CO5151 Advanced Agentic AI · Bảo vệ vòng 1\nHà Thanh Bình · Huỳnh Đức Nhâm · La Quang Huy",{x:0.7,y:4.3,w:8.6,h:0.7,fontFace:BF,fontSize:14,color:"CFE3DD",margin:0,isTextBox:true});
  s.addNotes("Giới thiệu nhóm và đề tài: agent hỗ trợ kỹ sư firmware, không chỉ tra cứu mà thiết kế có phản hồi từ simulator, DRC và trình biên dịch."); }
// 2 problem
{ const s=pres.addSlide(); s.background={color:PAPER}; n++; title(s,"Vấn đề: một sai số nhỏ làm hỏng cả board");
  s.addText([{text:"Kỹ sư phải đối chiếu datasheet, reference manual và SVD, rồi viết mã cấu hình thanh ghi.",options:{bullet:true,breakLine:true}},{text:"Sai một pin AF, một mức logic hay một giới hạn điện áp có thể phá chip.",options:{bullet:true,breakLine:true}},{text:"LLM trần hay bịa số và không biết khi nào nên từ chối hoặc hỏi lại.",options:{bullet:true,breakLine:true}},{text:"Mục tiêu: agent trả lời có nguồn, tự kiểm chứng bằng công cụ xác định, và đo được bằng split test niêm phong.",options:{bullet:true}}],{x:0.5,y:1.3,w:5.3,h:3.6,fontFace:BF,fontSize:16,color:SLATE,paraSpaceAfter:8,margin:0,isTextBox:true,valign:"top"});
  stat(s,6.3,1.3,3.2,"4","chip và RTOS được hỗ trợ"); stat(s,6.3,2.7,3.2,"32","công cụ qua 4 MCP server"); stat(s,6.3,4.0,3.2,"4.520","trang tài liệu chính hãng trong chỉ mục"); foot(s,n); }
// 3 architecture
{ const s=pres.addSlide(); s.background={color:PAPER}; n++; title(s,"Kiến trúc: state machine có checkpoint");
  s.addImage({path:path.join(__dirname,"architecture.png"),x:0.5,y:1.2,w:9.0,h:4.29*0.92*1.0>3.9?3.9:4.29,sizing:{type:"contain",w:9.0,h:3.9}});
  s.addText("INTAKE → PLAN → ACT⇄OBSERVE → CHECK → FINISH_GATE; HITL tạm dừng và resume; 4 MCP server; Gate G1–G5; Board State + DRC",{x:0.5,y:5.0,w:9,h:0.3,fontFace:BF,fontSize:12,color:SLATE,margin:0,isTextBox:true}); foot(s,n); s.addNotes("Runtime có SQLite checkpoint nên có thể tạm dừng để người duyệt rồi resume."); }
// 4 safety layers
{ const s=pres.addSlide(); s.background={color:PAPER}; n++; title(s,"Ba lớp xác định, đều là mã chứ không phải prompt");
  card(s,0.5,1.3,2.9,3.4,"1. Guardrail ở INTAKE","Lọc injection trực tiếp; kiểm điện áp theo rail (VDD/VDDH/VBUS) và lớp chân (TT/FT_c/FT); từ chối kèm trích giới hạn.");
  card(s,3.55,1.3,2.9,3.4,"2. Policy Engine","Trước mọi lời gọi công cụ: trần điện áp, hạn ngạch ghi file, chặn nội dung nhiễm (taint), chặn tham số quá lớn; ghi file cần người duyệt.");
  card(s,6.6,1.3,2.9,3.4,"3. Verification Gate","G1 nguồn, G2 mô phỏng, G3 DRC, G4 an toàn, G5 hoàn tất; câu trả lời không qua cổng thì không được kết thúc.");
  s.addText("Lesson memory: chỉ ghi khi simulator xác nhận một lần tự sửa.",{x:0.5,y:4.8,w:9,h:0.3,fontFace:BF,fontSize:13,italic:true,color:COPPER,margin:0,isTextBox:true}); foot(s,n); }
// 5 eval design
{ const s=pres.addSlide(); s.background={color:PAPER}; n++; title(s,"Đánh giá: split test niêm phong, grader khoá trước");
  s.addText([{text:"148 task tự xây: dev 50, test 98; C1–C8 và C10, cộng FI và C9 sinh từ task gốc.",options:{bullet:true,breakLine:true}},{text:"Chấm bằng grader xác định, không dùng LLM làm giám khảo; 3 seed; CI 95% bootstrap theo task.",options:{bullet:true,breakLine:true}},{text:"Khoá băm grader, task và snapshot agent được commit TRƯỚC khi có đầu ra test.",options:{bullet:true,breakLine:true}},{text:"Model duy nhất: gemini-3.8-flash cho mọi hệ.",options:{bullet:true}}],{x:0.5,y:1.3,w:5.2,h:3.4,fontFace:BF,fontSize:16,color:SLATE,paraSpaceAfter:8,margin:0,isTextBox:true,valign:"top"});
  const rows=[["Hệ","Mô tả"],["S0","LLM gọi trực tiếp"],["S1","RAG native"],["S2 / S2D","agent v1 (dữ liệu tay / thật)"],["S3@P7","agent v3 đầy đủ"]];
  s.addTable(rows.map((r,i)=>r.map(t=>({text:t,options:{bold:i===0,color:i===0?"FFFFFF":SLATE,fill:{color:i===0?INK:(i%2?MIST:PAPER)},fontFace:BF,fontSize:13}}))),{x:6.0,y:1.4,w:3.5,colW:[1.1,2.4],border:{type:"solid",color:"D5E2DD",pt:0.5},rowH:0.42}); foot(s,n); }
// 6 main results
{ const s=pres.addSlide(); s.background={color:PAPER}; n++; title(s,"S3@P7 đạt 85,4% TSR trên split test");
  s.addChart(pres.charts.BAR,[{name:"TSR (%)",labels:["S2","S1","S2D","S0","S3@P7"],values:[27.9,34.0,55.4,68.7,85.4]}],{x:0.5,y:1.2,w:5.6,h:3.9,barDir:"col",chartColors:[SOFT,SOFT,SOFT,SOFT,COPPER],showValue:true,dataLabelFontSize:12,dataLabelColor:SLATE,dataLabelPosition:"outEnd",catAxisLabelColor:SLATE,valAxisLabelColor:SLATE,valAxisMaxVal:100,valAxisMinVal:0,valGridLine:{color:"E3ECE8",size:0.5},catGridLine:{style:"none"},showLegend:false,showTitle:true,title:"TSR tổng, 98 task x 3 seed",titleFontSize:13,titleColor:SLATE,catAxisLabelFontSize:12,valAxisLabelFontSize:11});
  stat(s,6.6,1.3,3,"+16,7","điểm so với S0, CI [8,8–24,8], p<0,001"); stat(s,6.6,2.8,3,"+29,9","điểm so với S2D (agent v1 trên dữ liệu thật)"); s.addText("Chi phí 0,03 USD/task (giá cấu hình)",{x:6.6,y:4.4,w:3,h:0.5,fontFace:BF,fontSize:13,italic:true,color:SLATE,margin:0,isTextBox:true}); foot(s,n); s.addNotes("TSR gộp seed trước rồi trung bình theo task. Số liệu theo grader đã khoá."); }
// 7 by category
{ const s=pres.addSlide(); s.background={color:PAPER}; n++; title(s,"Lợi thế nằm ở thiết kế nhiều lượt có phản hồi");
  const labels=["C1","C2","C3","C4","C5","C6","C7","C8"];
  s.addChart(pres.charts.BAR,[{name:"S0",labels,values:[70.6,64.3,100,10.0,16.7,66.7,100,76.2]},{name:"S2D",labels,values:[98.0,61.9,0,0,0,53.3,100,95.2]},{name:"S3@P7",labels,values:[94.1,66.7,100,86.7,41.7,80.0,100,90.5]}],{x:0.5,y:1.2,w:6.3,h:3.9,barDir:"col",barGrouping:"clustered",chartColors:[SOFT,"6F8F88",COPPER],showLegend:true,legendPos:"b",legendFontSize:11,legendColor:SLATE,catAxisLabelColor:SLATE,valAxisLabelColor:SLATE,valAxisMaxVal:100,valAxisMinVal:0,valGridLine:{color:"E3ECE8",size:0.5},catGridLine:{style:"none"},catAxisLabelFontSize:12,valAxisLabelFontSize:11,showTitle:true,title:"TSR (%) theo nhóm task",titleFontSize:13,titleColor:SLATE});
  stat(s,7.1,1.3,2.5,"86,7%","C4: nhiều lượt có xung đột, so với 10,0% của S0 (p=0,004)"); s.addText("Điểm yếu: C5 chỉ 41,7%",{x:7.1,y:3.6,w:2.5,h:0.4,fontFace:HF,fontSize:15,bold:true,color:INK,margin:0,isTextBox:true}); s.addText("Một task bị guardrail từ chối oan ở cả 3 seed (4,2 V của nRF gán nhầm cho STM32).",{x:7.1,y:4.0,w:2.5,h:1.1,fontFace:BF,fontSize:12,color:SLATE,margin:0,isTextBox:true,valign:"top"}); foot(s,n); }
// 8 causal
{ const s=pres.addSlide(); s.background={color:PAPER}; n++; title(s,"Bằng chứng nhân quả và độ bền");
  stat(s,0.5,1.3,2.9,"80→60%","C6 an toàn điện khi bỏ guardrail xác định (A7); lặp lại phát hiện ở dev (100→60%)");
  stat(s,3.6,1.3,2.9,"101% vs 79%","Recovery Rate khi công cụ tri thức bị lỗi: S3@P7 so với S2D");
  if(C9) stat(s,6.7,1.3,2.9,C9.big,C9.label); else stat(s,6.7,1.3,2.9,"0%","ASR tấn công trực tiếp ở mọi hệ; gián tiếp 0/21 run phơi nhiễm");
  s.addText([{text:"Model nền tự kháng prompt injection nên C7 chưa tách được sanitize/taint khỏi khả năng của model.",options:{bullet:true,breakLine:true}},{text:"Lesson memory: 14 bài học được ghi ở 12/294 run, dùng lại 2 lần trong cùng hội thoại; chưa kiểm được lợi ích (H4).",options:{bullet:true,breakLine:true}},{text:"Trần thời gian runtime phải nâng từ 600 s lên 2400 s vì gateway chậm; một phép đo C9 ở dev bị cắt oan do trần này.",options:{bullet:true}}],{x:0.5,y:3.2,w:9,h:1.9,fontFace:BF,fontSize:14,color:SLATE,paraSpaceAfter:6,margin:0,isTextBox:true,valign:"top"}); foot(s,n); }
// 9 blind
{ const s=pres.addSlide(); s.background={color:PAPER}; n++; title(s,"Kiểm nhãn mù: grader khoá bảo thủ hơn annotator");
  const rows=[["Nhóm","Độ khớp","Grader","Nhãn mù"],["C4 xung đột","42/42 mục nêu chủ động","86,7","93,3"],["C5 checklist","95,6% (κ=0,91)","41,7","58,3"],["C6 an toàn","từ chối kiểu trích dẫn bị chấm warn","80,0","90,0"],["C8 từ chối","95,2% (κ=0,53)","90,5","100"]];
  s.addTable(rows.map((r,i)=>r.map((t,j)=>({text:t,options:{bold:i===0,color:i===0?"FFFFFF":SLATE,fill:{color:i===0?INK:(i%2?MIST:PAPER)},fontFace:BF,fontSize:13,align:j>1?"center":"left"}}))),{x:0.5,y:1.3,w:9,colW:[2.0,4.2,1.4,1.4],border:{type:"solid",color:"D5E2DD",pt:0.5},rowH:0.46});
  s.addText([{text:"Tổng S3@P7: 85,4% → 89,1%; S0: 68,7% → 74,5%; xếp hạng giữa các hệ không đổi.",options:{bullet:true,breakLine:true}},{text:"Annotator là subagent độc lập, đọc gói xáo trộn ẩn tên hệ. Là model, không phải người.",options:{bullet:true,breakLine:true}},{text:"Grader không bị sửa sau khi thấy đầu ra; báo cả hai con số.",options:{bullet:true}}],{x:0.5,y:3.8,w:9,h:1.3,fontFace:BF,fontSize:14,color:SLATE,paraSpaceAfter:6,margin:0,isTextBox:true,valign:"top"}); foot(s,n); }
// 10 demo
{ const s=pres.addSlide(); s.background={color:PAPER}; n++; title(s,"Demo ghi sẵn trên UI");
  const items=[["D1","PWM 20 kHz + cổng phê duyệt ghi file"],["D2","Tự sửa lỗi PLL nhờ simulator và Gate"],["D3","DRC chặn cảm biến 1,8 V nối I2C 3,3 V"],["D5","Ghi rồi dùng lại bài học (cùng hội thoại)"],["C6","Từ chối 5 V vào VDD nRF52840, trích giới hạn"],["C7","Chặn ghi file ../../etc"]];
  items.forEach((it,i)=>{ const col=i%2, row=Math.floor(i/2); const x=0.5+col*4.6, y=1.3+row*1.25; s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x,y,w:4.4,h:1.05,fill:{color:MIST},line:{color:MIST},rectRadius:0.08}); s.addText(it[0],{x:x+0.15,y:y+0.1,w:0.9,h:0.85,fontFace:HF,fontSize:22,bold:true,color:COPPER,margin:0,isTextBox:true,valign:"middle"}); s.addText(it[1],{x:x+1.05,y:y+0.1,w:3.2,h:0.85,fontFace:BF,fontSize:13,color:SLATE,margin:0,isTextBox:true,valign:"middle"}); });
  s.addText("11 kịch bản ghi sẵn trong viewer; D3 là kiểm tra DRC của Board State, chưa phải luật Policy Engine P6.",{x:0.5,y:5.0,w:9,h:0.3,fontFace:BF,fontSize:12,italic:true,color:SLATE,margin:0,isTextBox:true}); foot(s,n); }
// 11 limits + next
{ const s=pres.addSlide(); s.background={color:INK}; n++;
  s.addText("Hạn chế trung thực và việc tiếp theo",{x:0.5,y:0.3,w:9,h:0.8,fontFace:HF,fontSize:30,bold:true,color:"FFFFFF",margin:0,isTextBox:true,valign:"middle"});
  s.addText([{text:"Task tự viết, chưa có người duyệt độc lập; nhãn mù do model",options:{bullet:true,breakLine:true}},{text:"Một model, một gateway; giá chưa đối chiếu",options:{bullet:true,breakLine:true}},{text:"Lesson memory chưa có bằng chứng lợi ích (A5 chưa chạy ở test)",options:{bullet:true,breakLine:true}},{text:"Guardrail từ chối oan khi một câu mô tả hai chip (C5-012)",options:{bullet:true,breakLine:true}},{text:"S3@P5, A7, FI, C9 chỉ chạy trên tập con ở test",options:{bullet:true}}],{x:0.5,y:1.3,w:4.4,h:3.7,fontFace:BF,fontSize:14,color:"E4EFEB",paraSpaceAfter:8,margin:0,isTextBox:true,valign:"top"});
  s.addText("Tiếp theo (trước vòng 2, 9/12)",{x:5.2,y:1.3,w:4.3,h:0.4,fontFace:HF,fontSize:17,bold:true,color:COPPER,margin:0,isTextBox:true});
  s.addText([{text:"Sửa phép gán điện áp theo chip trong guardrail",options:{bullet:true,breakLine:true}},{text:"Cải thiện nhận diện cụm từ chối của grader C6",options:{bullet:true,breakLine:true}},{text:"Chạy A5 ở test; tìm mẫu lỗi lặp để kiểm H4",options:{bullet:true,breakLine:true}},{text:"Người duyệt độc lập cho task test C7 và C10",options:{bullet:true}}],{x:5.2,y:1.8,w:4.3,h:3.1,fontFace:BF,fontSize:14,color:"E4EFEB",paraSpaceAfter:8,margin:0,isTextBox:true,valign:"top"}); }
pres.writeFile({fileName:path.join(__dirname,"slides_round1.pptx")}).then(()=>console.log("ok"));
