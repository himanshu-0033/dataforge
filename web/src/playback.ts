export class PlaybackAcknowledger {
  private generation=0;
  private active:string|null=null;
  constructor(private send:(responseId:string,status:'playing'|'completed'|'interrupted')=>Promise<unknown>,private durationMs=1250){}
  start(responseId:string,durationMs=this.durationMs){
    if(this.active) void this.send(this.active,'interrupted');
    this.active=responseId;
    const own=++this.generation; void this.send(responseId,'playing');
    setTimeout(()=>{if(own===this.generation){this.active=null;void this.send(responseId,'completed')}},durationMs);
  }
  interrupt(responseId:string){++this.generation;this.active=null;void this.send(responseId,'interrupted')}
  stop(){++this.generation;this.active=null}
}
